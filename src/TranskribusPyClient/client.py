# -*- coding: utf-8 -*-

"""
    Transkribus REST API for Python clients
    
    WORK IN PROGRESS...

    Copyright Xerox(C) 2016 H. Déjean, JL. Meunier

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.
    
    
    Developed  for the EU project READ. The READ project has received funding 
    from the European Union’s Horizon 2020 research and innovation programme 
    under grant agreement No 674943.
    
"""
import os
import logging
import types
import requests
import codecs
import json
import shutil
import cPickle

import libxml2


def getStoredCredentials(bAsk=False):
    login, pwd = None, None
    try:
        import Transkribus_credential
        login, pwd = Transkribus_credential.login, Transkribus_credential.password
        del Transkribus_credential
    except ImportError:
        logging.warn("No Transkribus credentials. Consider having a 'Transkribus_credential.py' Python module or use a persistent session using --persist.")
        if bAsk:
            login, pwd = raw_input("Enter your Transkribus login: "), raw_input("Enter your Transkribus password: ")
    if login == None or pwd == None:
        raise ValueError("Missing Transkribus credentials!")
    return login, pwd
        
class TranskribusClient():
    """
    
    See web sites below for a detailed description of the server API:
    
    - https://transkribus.eu/wiki/index.php/REST_Interface
    - https://transkribus.eu/TrpServer/rest/application.wadl
    - https://github.com/Transkribus

    -- Query Parameters
    Most parameters can be passed as string.
    
    Transkribus specifies some of them as xs:int for instance. 
    In that case, you can pass an int or a string, since we format them using the pythoninc "%s".
    
        
    -- Proxies
    If you need to use a proxy, you can configure individual requests with the proxies argument to the login method:
    
    myproxies = {
      'http': 'http://10.10.1.10:3128',
      'https': 'http://10.10.1.10:1080',
    }
    
    clientObj.auth_login("_login_", "_pwd_", proxies=myproxies)
    
    You can also configure proxies by setting the environment variables HTTP_PROXY and HTTPS_PROXY.
    
    $ export HTTP_PROXY="http://10.10.1.10:3128"
    $ export HTTPS_PROXY="http://10.10.1.10:1080"
    
    To use HTTP Basic Auth with your proxy, use the http://user:password@host/ syntax:
    proxies = {'http': 'http://user:pass@10.10.1.10:3128/'}
    
    To give a proxy for a specific scheme and host, use the scheme://hostname form for the key. This will match for any request to the given scheme and exact hostname.
    
    proxies = {'http://10.20.1.128': 'http://10.10.1.10:5323'}
    Note that proxy URLs must include the scheme.


    """
    
    #timestamp file extension
    POSTFIX_MAX_TX = "_max.ts"
    
    #persistent session folder and filename
    sSESSION_FOLDER     = ".trnskrbs"
    sSESSION_FILENAME   = "session.txt"
            
    #--- --- INIT --- -------------------------------------------------------------------------------------------------------------    
    def __init__(self, sServerUrl="https://transkribus.eu/TrpServer"
                 , proxies={}
                 , loggingLevel=logging.WARN):
        self._sessionID = None  # if logged in, id of the session, None otherwise
        self._dProxies  = {}    # proxy settings

        # Raise or lower this setting according to the amount of debugging
        # output you would like to see.  See http://docs.python.org/lib/module-logging.html
        logging.basicConfig(level=loggingLevel)

        self.setProxies(proxies)
        
        #self._assertUrl(sServerRootUrl)
        if sServerUrl.endswith("/"): sServerUrl = sServerUrl[:-1]
        
        self.sREQ_auth_login        = sServerUrl + '/rest/auth/login'
        self.sREQ_auth_logout       = sServerUrl + '/rest/auth/logout'
        
#         self.sREQ_ReqListRNNModel   = sServerUrl + '/rest/recognition/nets'
#         self.sREQ_ReqListDict       = sServerUrl + '/rest/recognition/dicts'
#         self.sREQ_ReqRNN            = sServerUrl + '/rest/recognition/rnn?' +'collId=%s&modelName=%s&dict=%s&id=%s&pages=%s'
#         
#         
#         self.sREQ_LABlocks          = sServerUrl + '/rest/LA/blocks?'+'collId=%s&id=%s&page=%s'
#     
#         self.sREQ_LALines           = sServerUrl + '/rest/LA/lines'
#         self.sREQ_LABaseLines       = sServerUrl + '/rest/LA/baselines'
        self.sREQ_collection                        = sServerUrl + '/rest/collections'
        self.sREQ_collection_listEditDeclFeats      = sServerUrl + '/rest/collections/%s/listEditDeclFeats'
        self.sREQ_collection_list                   = sServerUrl + '/rest/collections/%s/list'
        self.sREQ_collection_createCollection       = sServerUrl + '/rest/collections/createCollection'
        self.sREQ_collection_fulldoc                = sServerUrl + '/rest/collections/%s/%s/fulldoc'
        self.sREQ_collection_fulldoc_xml            = sServerUrl + '/rest/collections/%s/%s/fulldoc.xml'
        self.sREQ_collections_addDocToCollection    = sServerUrl + '/rest/collections/%s/addDocToCollection'
        self.sREQ_collections_duplicate             = sServerUrl + '/rest/collections/%s/%s/duplicate'
#         self.sREQ_GetPAGEXML        = sServerUrl + '/rest/collections/%s/%s/%s'
#         self.sREQ_PostPAGEXML       = sServerUrl + '/rest/collections/%s/%s/%s/text'

    #--- --- auth --- -------------------------------------------------------------------------------------------------------------
        
    def auth_login(self, sLogin, sPwd, bPersist=True):
        """
        login to the server
        If bPersistent is True, the session token is persisted on disk. 
        Further calls from another process can be made without login by using reusePersistentSession method
        Return True or raise an exception
        """
        if self._sessionID:
            self._raiseError(Exception, "You are already logged in. Please logout before logging in.")
            
        data = {'user': sLogin, 'pw': sPwd}
        resp = self.POST(self.sREQ_auth_login, data = {'user': sLogin, 'pw': sPwd}, bAppXml=False)
        del data
        resp.raise_for_status()
        
        ##extract sessionID from xml
        lsSessionId = self.xmlParse_xpathEval_getContent(resp.text, "//sessionId/text()")
        
        self.setSessionId(lsSessionId[0])
        
        if bPersist: self.setPersistentSession()

        return True  

    def auth_logout(self):
        """
        Logout from the server, remove any persistent session token from disk
        Return True or raise an exception
        """
        try: self.cleanPersistentSession()
        except: pass
        
        try:
            resp = self.POST(self.sREQ_auth_logout)
            resp.raise_for_status()
        finally:
            self._sessionID = None

        return True

    #--- --- collections --- -------------------------------------------------------------------------------------------------------------
    def collections_listEditDeclFeats(self, colId):
        """
        Return the Transkribus data structure (XML as a DOM) 
        or raise an exception

        Caller must free the DOM using the xmlFreeDoc method of this object.
        """
        self._assertLoggedIn()
        myReq = self.sREQ_collection_listEditDeclFeats % (colId)
        resp = self.GET(myReq)
        resp.raise_for_status()

        #we get some json serialized data
        return self.xmlParseDoc(resp.text)

    def collections_list(self, colId, index=None, nValues=None, sortColumn=None, sortDirection=None):
        """
        Return the Transkribus data structure (Pythonic data) 
        or raise an exception
        
        Undocumented parameters, sorry.
        """
        self._assertLoggedIn()
        myReq = self.sREQ_collection_list % (colId)
        params = self._buidlParamsDic(index=None, nValues=None, sortColumn=None, sortDirection=None)
        resp = self.GET(myReq, params=params)
        resp.raise_for_status()

        #we get some json serialized data
        return json.loads(resp.text)
    
    def collection_createCollection(self, sName):
        """
        create a new collectin with given name.
        Return the collection unique identifier: colId   (as a string)
        """
        self._assertLoggedIn()
        myReq = self.sREQ_collection_createCollection
        resp = self.POST(myReq, {'collName':sName }, bAppXml=False) #False-> no content-type in HTTP header.
        resp.raise_for_status()
        return resp.text
        
    def collection_deleteCollection(self, colId):
        """
        delete a collection
        Return True
        """
        self._assertLoggedIn()
        myReq = self.sREQ_collection+"/%s"%colId
        resp = self.DELETE(myReq, { 'collId':colId })
        resp.raise_for_status()
        return resp.text

    def collection_deleteDocument(self, colId, docId):
        """
        delete a document from a collection
        Return True
        """
        self._assertLoggedIn()
        myReq = self.sREQ_collection_collection%(colId, docId)
        resp = self.DELETE(myReq, { 'collId':colId, 'id':docId })
        resp.raise_for_status()
        return resp
 

    def collections_fulldoc(self, colId, docId, nrOfTranscripts=None):
        """
        Return the Transkribus data structure ( Pythonic data ) 
        or raise an exception
        
        nrOfTranscripts can be either -1 (all), 0 (no transcripts) or any positive max. value of transcripts you want to receive per page.
        """
        self._assertLoggedIn()
        myReq = self.sREQ_collection_fulldoc % (colId,docId)
        params = self._buidlParamsDic(nrOfTranscripts=None)
        resp = self.GET(myReq, params=params)
        resp.raise_for_status()

        #we get some json serialized data
        return json.loads(resp.text)


    def collections_fulldoc_xml(self, colId, docId, nrOfTranscripts=None, bParse=True):
        """
        Return the Transkribus data structure (either parsed as a DOM or as a serialized XML, , i.e. a unicode string)
        or raise an exception
        
        If you get a DOM, you need to free it afterward using the xmlFreeDoc method.
        
        nrOfTranscripts can be either -1 (all), 0 (no transcripts) or any positive max. value of transcripts you want to receive per page.
        """
        self._assertLoggedIn()
        myReq = self.sREQ_collection_fulldoc_xml % (colId,docId)
        params = self._buidlParamsDic(nrOfTranscripts=None)
        resp = self.GET(myReq, params=params)
        resp.raise_for_status()
       
        #we should get some json serialized data   
        if bParse:
            return self.xmlParseDoc(resp.text)
        else:     
            return resp.text

    def collections_addDocToCollection(self, colId, docId):
        """
        Add document docId to collection colId   (this is not a copy!!)
        
        Return True or raises an Exception
        
        NOTE the REST API does not return the new DocId... :-/
        """
        self._assertLoggedIn()
        #myReq = self.sREQ_collections_addDocToCollection % (colId) + "?id=%s"%docId
        myReq = self.sREQ_collections_addDocToCollection % (colId)
        resp = self.POST(myReq, {'id':docId} )
        resp.raise_for_status()
        # return resp.text  #return "" or something like " document is already in collection"
        #maise raise an exception upon server error
        # requests.exceptions.HTTPError: 500 Server Error: Internal Server Error for url: https://transkribus.eu/TrpServer/rest/collections/3820/addDocToCollection?id=66666
        return True
        
    def collections_copyDocToCollection(self, colIdFrom, docId, colIdTo, name=None):
        """
        Copy document docId from collection colIdFrom to collection colIdTo
        The document is renamed if a name is provided
        
        Return True or raises an Exception
        """
        self._assertLoggedIn()
        #myReq = self.sREQ_collections_addDocToCollection % (colId) + "?id=%s"%docId
        myReq = self.sREQ_collections_duplicate % (colIdFrom, docId)
        if not name:
            name = -1
            #let's find it! :-(
            lDocDic = self.collections_list(colIdFrom)
            for docDic in lDocDic:
                if docDic['docId'] == docId:
                    name = docDic['title']
                    break
            if name == -1: raise Exception("Document '%d' is not in source collection '%d'"%(docId, colIdFrom))
        self._assertString(name, "name")            
        resp = self.POST(myReq, {'name':name, 'collId':colIdTo} )
        """
    NO WAY TO GET THE CREATED ID???
        print resp.headers
        print resp.text
> TranskribusCommands/do_copyDocToCollec.py 3571 3820 8251 --persist
-login- Try reusing persistent session ... OK!
- checking names of each document in source collection '3571'
- copying from collection 3571 to collection '3820' the 1 documents:  8251  ('MM_1_012'){'Content-Length': '5', 'Keep-Alive': 'timeout=5, max=100', 'Server': 'Apache/2.4.6 (CentOS) OpenSSL/1.0.1e-fips PHP/5.4.16 mod_wsgi/3.4 Python/2.7.5', 'Connection': 'Keep-Alive', 'Access-Control-Allow-Credentials': 'true', 'Date': 'Mon, 28 Nov 2016 14:52:53 GMT', 'Access-Control-Allow-Origin': 'http://www.transcribe-bentham.da.ulcc.ac.uk', 'Access-Control-Allow-Headers': 'Content-Type', 'Content-Type': 'text/plain;charset=utf-8', 'P3P': 'CP="ALL IND DSP COR ADM CONo CUR CUSo IVAo IVDo PSA PSD TAI TELo OUR SAMo CNT COM INT NAV ONL PHY PRE PUR UNI"'}
31033
      
        """
        resp.raise_for_status()
        # return resp.text  #return "" or something like " document is already in collection"
        #maise raise an exception upon server error
        # requests.exceptions.HTTPError: 500 Server Error: Internal Server Error for url: https://transkribus.eu/TrpServer/rest/collections/3820/addDocToCollection?id=66666
        return True
        
    def download_collection(self, colId, collDir, bForce=False):        
        """
        Convenience method, not provided directly by the Transkribus API.
        
        Lazy download of the colId collection into the collDir folder.
        Lazy, because it does not download a document that is not more recent than the one one disk. It uses page timestamp to decide.
        Both the XML and images are fetched from the server. 
        
        The destination folder is created if required.
        It also creates 1 sub-folder per document in the collection. If the folder exists, raise an exception, unless bForce is True in which case, the folder is removed and recreated.
        
        Return the maximum timestamp over all pages of the collection.
        """
        logging.info("- downloading collection %s into folder %s    (bForce=%s)"%(colId, collDir, bForce))

        if not os.path.exists(collDir): os.mkdir(collDir)
        
        coll_max_ts = None
        #list collection content
        lDocInfo = self.collections_list(colId)
        # store collections metadata 
        with codecs.open(collDir+os.sep+"trp.json", "wb",'utf-8') as fd: json.dump(lDocInfo, fd, indent=2)
        
        for docInfo in lDocInfo:
            docId = docInfo['docId']  #int here!!!
            docDir = os.path.join(collDir, str(docId))

            #Maybe we already have this version of the document??
            stored_doc_ts_file = docDir+self.POSTFIX_MAX_TX
            if os.path.exists(stored_doc_ts_file): 
                with open(stored_doc_ts_file, 'r') as fd: stored_doc_ts = fd.read()
                stored_doc_ts = int(stored_doc_ts)
            else:
                stored_doc_ts = None    
                            
            doc_max_ts = self.download_document(colId, docId, docDir, min_ts=stored_doc_ts, bForce=bForce)
            
            assert doc_max_ts >= stored_doc_ts, "Server side data older than disk data???"
            if doc_max_ts == stored_doc_ts:
                #NOTE: we did not check each page!!
                logging.info("\tcollection %s, document %s, data on disk is UP-TO-DATE - I do nothing else."%(colId, docId))
            else:
                with open(stored_doc_ts_file, "w") as fd: fd.write("%s"%doc_max_ts) 
            
            coll_max_ts = max(coll_max_ts, doc_max_ts)
            
        logging.info("- DONE (downloaded collection %s into folder %s    (bForce=%s))"%(colId, collDir, bForce))
        return coll_max_ts
        

    def download_document(self, colId, docId, docDir, min_ts=None, bForce=False):        
        """
        Convenience method, not provided directly by the Transkribus API.
        
        Lazy download of the colId, docId document into the docDir folder.
        Lazy, because it does not download a document that is not more recent than the given timestamp. It uses page timestamp to decide.
        Both the XML and images are fetched from the server. 
        
        If the destination folder exists, raise an exception, unless bForce is True in which case, the folder is removed and recreated.
        
        Return the maximum timestamp over all pages of the document.
        """
        logging.info("- downloading collection %s, document %s  into folder %s    (bForce=%s)"%(colId, docId, docDir, bForce))
        
        trp = self.collections_fulldoc(colId, docId, nrOfTranscripts=1)
        pageList = trp["pageList"]
        doc_max_ts = max( [page['tsList']["transcripts"][0]['timestamp'] for page in pageList['pages'] ] )

        if doc_max_ts <= min_ts:
            #no need to download
            #NOTE: we do not check each page!!
            return doc_max_ts

        #Ok, we must refresh the disk
        if os.path.exists(docDir):
            #we need to deal with this existing folder.
            if bForce:
                logging.warn("\t\t REMOVING OBSOLETE DATA in %s...  "%docDir)
                shutil.rmtree(docDir)
                os.mkdir(docDir)
                logging.warn("\t\tDone removal.")
            else:
                logging.warn("\t\t**** EXISTING DATA ON DISK in %s - I do nothing unless you force the overwriting"%docDir)
                raise Exception("Existing data on disk, cannot download collection %s, document %s into folder %s, unless bForce=True"%(colId, docId, docDir))

        else:
            os.mkdir(docDir)

        # store document metadata 
        with codecs.open(docDir+os.sep+"trp.json", "wb",'utf-8') as fd: json.dump(trp, fd, indent=2)
        
        for page in pageList['pages']:
            pagenum= page['pageNr']
            logging.info("\t\t- page %s"%pagenum)
            imgFileName = page['imgFileName']
            urlImage= page['url']
            dicTranscript0 = page['tsList']["transcripts"][0]
            urlXml = dicTranscript0['url']
            
            #Now store the image and pageXml
            destImgFilename = docDir + os.sep + imgFileName
            logging.info("\t\t\t%s"%destImgFilename)
            resp = self.GET(urlImage, stream=True)
            with open(destImgFilename, 'wb') as fd:
                for chunk in resp.iter_content(10240):
                    fd.write(chunk)                
            sBaseName, _ = os.path.splitext(imgFileName)
            destXmlFilename = docDir + os.sep + sBaseName + ".pxml"
            logging.info("\t\t\t%s"%destXmlFilename)
            resp = self.GET(urlXml)
            savefile=codecs.open(destXmlFilename,'wb','utf-8')
            savefile.write(resp.text)  
            savefile.close()  
            
        with open(docDir+os.sep+"max.ts", "w") as fd: fd.write("%s"%doc_max_ts) 

        logging.info("- DONE (downloaded collection %s, document %s into folder %s    (bForce=%s))"%(colId, docId, docDir, bForce))
        return doc_max_ts

    # --------------------------------------------------------------------------------------------------------------

#     def getDocumentFromServer(self, colid, docId):
#         """
#             get XML doc: 
#                 then for each page:
#                     get pagexml
#                     get image?
#                 
#             generate structure a la Transkribus export
#                 FOLDER
#                     pages/ (pageXML file one per per)
#                     Images (one per per)
#         """
#         import trpDoc
#     
#         print colid, docId
# #         sessionID = self.RESTLogin()
# #         print sessionID
#     
#         myReq = self.sREQ_collection_fulldoc % (colid,docId)
# #         print myReq
#         res = self.GET(myReq)
#         print res
#         print res.status_code
#         print type(res.status_code)
#         print  dir(res)
# #         print res.text
#         myJSONTrpDoc = trpDoc.getJSONPages(res.text)
# #         return myJSONTrpDoc
#     
#         for docName,imgFileName,pagenum,url,lTx in myJSONTrpDoc:
#             print (docName,imgFileName,pagenum,url,lTx)
#             if not os.path.exists(docName):
#                 os.mkdir(docName)
#             if not os.path.exists("%s%s%s"%(docName,os.sep,'page')):
#                 os.mkdir("%s%s%s"%(docName,os.sep,'page'))                
#             res = self.GET(lTx[0][1])
# #             print '%s%s%s%s%sxml'%(docName,os.sep,'page',os.sep,imgFileName[:-4])
# #             print lTx[0][1]
#             savefile=codecs.open('%s%s%s%s%s.xml'%(docName,os.sep,'page',os.sep,imgFileName[:-4]),'a','utf-8')
#             savefile.write(res.text)
# 
#         

        
    # --- Session Utilities --- ----------------------------------------------------------------
    def getStoredCredentials(cls, bAsk=False):
        """
        alias for module function
        """
        return getStoredCredentials(bAsk)
    getStoredCredentials = classmethod(getStoredCredentials)
    
    def getSessionId(self):
        """
        return the current session ID or None if not logged in
        """
        return self._sessionID
    
    def setSessionId(self, sessionId):
        """
        set the session ID
        """
        self._sessionID = sessionId
        #the HTTP header that will be constantly used
        return self._sessionID

    def reusePersistentSession(self):
        """
        reuse the session Id from the session file, if any
        raise an Exception if no session stored
        return True
        """
        sSessionFilename = os.path.join(self.sSESSION_FOLDER, self.sSESSION_FILENAME)
        with open(sSessionFilename, "rb") as fd:
            sSessionId = cPickle.load(fd)
        self.setSessionId(sSessionId)
        return True
    
    def setPersistentSession(self):
        """
        persist the session. 
        To be called after login!
        
        return True or raises an exception
        """
        #The folder
        if os.path.exists(self.sSESSION_FOLDER):
            if not os.path.isdir(self.sSESSION_FOLDER):
                sMsg = "'%s' exists and is not a directory"%self.sSESSION_FOLDER
                raise Exception(sMsg)
        else:
            os.mkdir(self.sSESSION_FOLDER)
        os.chmod(self.sSESSION_FOLDER, 0700)
    
        #the file
        sSessionFilename = os.path.join(self.sSESSION_FOLDER, self.sSESSION_FILENAME)
        if os.path.exists(sSessionFilename):
            if  os.path.isfile(sSessionFilename):
                os.unlink(sSessionFilename)
            else:
                sMsg = "'%s' exists and is not a regular file"%sSessionFilename
                raise Exception(sMsg)
    
        with open(sSessionFilename, "wb") as fd:
            cPickle.dump(self.getSessionId(), fd)
        os.chmod(sSessionFilename, 0600)    
    
        return True

    def cleanPersistentSession(self):
        """
        remove from disk any persistent session token. Idempotent (no exception if disk is already clean)
        return True or raises an exception
        """    
                #The folder
        if os.path.exists(self.sSESSION_FOLDER):
            if os.path.isdir(self.sSESSION_FOLDER):
                #the file
                sSessionFilename = os.path.join(self.sSESSION_FOLDER, self.sSESSION_FILENAME)
                if os.path.exists(sSessionFilename):
                    if  os.path.isfile(sSessionFilename):
                        os.unlink(sSessionFilename)
                    else:
                        #should be a file!!
                        sMsg = "'%s' exists and is not a regular file"%sSessionFilename
                        raise Exception(sMsg)
            else:
                #should be a directory if it exists!!
                sMsg = "'%s' exists and is not a directory"%self.sSESSION_FOLDER
                raise Exception(sMsg)
                        
        return True
    
    # --- HTTP Utilities --- ------------------------------------------------------------------
    
    def setProxies(self, proxies):
        """
        Proxies
        If you need to use a proxy, you can configure individual requests with the proxies argument to the login method:
        
        myproxies = {
          'http': 'http://10.10.1.10:3128',
          'https': 'http://10.10.1.10:1080',
        }
        
        You can also configure proxies by setting the environment variables HTTP_PROXY and HTTPS_PROXY.
        
        $ export HTTP_PROXY="http://10.10.1.10:3128"
        $ export HTTPS_PROXY="http://10.10.1.10:1080"
        
        To use HTTP Basic Auth with your proxy, use the http://user:password@host/ syntax:
        proxies = {'http': 'http://user:pass@10.10.1.10:3128/'}
        
        To give a proxy for a specific scheme and host, use the scheme://hostname form for the key. This will match for any request to the given scheme and exact hostname.
        
        proxies = {'http://10.20.1.128': 'http://10.10.1.10:5323'}
        Note that proxy URLs must include the scheme.

        return True or raise an exception 
        """
        self._assertDict(proxies, "Proxy definition")
        self._dProxies = proxies
        for sProtocol, sUrl in self._dProxies.items():
            logging.info("- %s proxy set to : '%s'"%(sProtocol, sUrl))
        return True
        
    def POST(self, sRequest, params={}, data={}, bAppXml=True):
        dHeader = {'Cookie':'JSESSIONID=%s'%self._sessionID}
        if bAppXml: dHeader['Content-type'] = 'application/xml'
            
        return requests.post(sRequest, params=params, headers=dHeader
                             , proxies=self._dProxies, data=data, verify=False)        

    def DELETE(self, sRequest, params={}, data={}):
        return requests.delete(sRequest, params=params, headers={'Cookie':'JSESSIONID=%s'%self._sessionID}
                               , proxies=self._dProxies, data=data, verify=False)        
        
    def GET(self, sRequest, params={}, stream=None):
        if stream == None: #not sure what is the default value...
            return requests.get(sRequest, params=params, headers={'Cookie':'JSESSIONID=%s'%self._sessionID, 'Content-type':'application/xml'}
                                , proxies=self._dProxies, verify=False)
        else:
            return requests.get(sRequest, params=params, headers={'Cookie':'JSESSIONID=%s'%self._sessionID, 'Content-type':'application/xml'}
                                , proxies=self._dProxies, verify=False, stream=stream)
            

    def _buidlParamsDic(self, **kwargs):
        """
        self._buidlParamsDic(a=None, b=2, c=3, d=None)  --> {'c': 3, 'b': 2}
        """
        return {k:v for k,v in kwargs.items() if v != None}
    
    # --- XML Utilities --- -------------------------------------------------------------------

    def xmlParseDoc(self, sXml):
        """
        Parse a serialized XML and return a DOM, which the caller must free later on!
        """
        return libxml2.parseDoc(sXml.encode('utf-8'))
    
    def xmlFreeDoc(self, doc):
        return doc.freeDoc()
    
    def xpathEval(self, domDoc, sXpathExpr):
        """
        run some XPATH expression on the dom
        """
        ctxt = domDoc.xpathNewContext()
        ret = ctxt.xpathEval(sXpathExpr)
        ctxt.xpathFreeContext()
        return ret

    def xmlParse_xpathEval_getContent(self, sXml, sXpathExpr):
        """
        run some XPATH expression on the response payload, considered as a serialized XML
        """
        domDoc = self.xmlParseDoc(sXml)
        ctxt = domDoc.xpathNewContext()
        lNd = ctxt.xpathEval(sXpathExpr)
        ret = [nd.getContent() for nd in lNd]
        ctxt.xpathFreeContext()
        self.xmlFreeDoc(domDoc)
        return ret

    
    # --- Errors handling --- -------------------------------------------------------------------

    def _raiseError(self, exceptionClass, msg):
        logging.error( "%s - %s"%(exceptionClass.__name__, msg) )
        raise exceptionClass(msg)
    
#     def _assertUrl(self, sUrl):
#         """
#         check validity of the url
#         """
#         if not type(sUrl) == types.StringType: 
#             return self._raiseError(ValueError, "URL parameter must be a string")
#         if not ( sUrl.lower().startswith("https://") or sUrl.lower().startswith("http://") ): 
#             return self._raiseError(ValueError, "Invalid protocol in URL")

    def _assertLoggedIn(self):
        if not self._sessionID: 
            self._raiseError(Exception, "Not logged in!")
    
    def _assertDict(self, obj, sObjName=""):
        if not type(obj) == types.DictionaryType: 
            return self._raiseError(TypeError, "%s must be a dictionary."%sObjName)
        
    def _assertString(self, obj, sObjName=""):
        if type(obj) not in [types.StringType, types.UnicodeType]: 
            return self._raiseError(TypeError, "%s must be a string. Got '%s'"%(sObjName,`obj`))
        
        
        
        
        
        
        
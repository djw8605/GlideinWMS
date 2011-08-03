#
# Project:
#   glideinWMS
#
# File Version: 
#
# Description:
#   This module implements the functions needed to advertize
#   and get resources from the Collector
#
# Author:
#   Igor Sfiligoi (Sept 15th 2006)
#

import condorExe
import condorMonitor
import condorManager
import os
import copy
import time
import string
import pubCrypto
from sets import Set
import symCrypto
import logging
import logSupport

############################################################
#
# Configuration
#
############################################################

class FrontendConfig:
    def __init__(self):
        # set default values
        # user should modify if needed

        # The name of the attribute that identifies the glidein
        self.factory_id = "glidefactory"
        self.factory_global = "glidefactoryglobal"
        self.client_id = "glideclient"
        self.client_global = "glideclientglobal"
        self.factoryclient_id = "glidefactoryclient"

        #Default the glideinWMS version string
        self.glideinwms_version = "glideinWMS UNKNOWN"

        # String to prefix for the attributes
        self.glidein_attr_prefix = ""

        # String to prefix for the parameters
        self.glidein_param_prefix = "GlideinParam"
        self.encrypted_param_prefix = "GlideinEncParam"

        # String to prefix for the monitors
        self.glidein_monitor_prefix = "GlideinMonitor"

        # String to prefix for the requests
        self.client_req_prefix = "Req"

        # The name of the signtype
        self.factory_signtype_id = "SupportedSignTypes"


        # Should we use TCP for condor_advertise?
        self.advertise_use_tcp = False
        # Should we use the new -multiple for condor_advertise?
        self.advertise_use_multi = False

        self.condor_reserved_names = ("MyType", "TargetType", "GlideinMyType", "MyAddress", 'UpdatesHistory', 'UpdatesTotal', 'UpdatesLost', 'UpdatesSequenced', 'UpdateSequenceNumber', 'DaemonStartTime')


# global configuration of the module
frontendConfig = FrontendConfig()

#####################################################
# Exception thrown when multiple executions are used
# Helps handle partial failures

class MultiExeError(condorExe.ExeError):
    def __init__(self, arr): # arr is a list of ExeError exceptions
        self.arr = arr

        # First approximation of implementation, can be improved
        str_arr = []
        for e in arr:
            str_arr.append('%s' % e)

        str = string.join(str_arr, '\\n')

        condorExe.ExeError.__init__(self, str)

############################################################
#
# User functions
#
############################################################
def findGlobals(factory_pool,factory_identity,
                 additional_constraint=None): 
    global frontendConfig
    status_constraint='(GlideinMyType=?="%s")'%frontendConfig.factory_global
    if not ((factory_identity==None) or (factory_identity=='*')): # identity checking can be disabled, if really wanted
        # filter based on AuthenticatedIdentity
        status_constraint+=' && (AuthenticatedIdentity=?="%s")'%factory_identity
    if additional_constraint!=None:
        status_constraint="%s && (%s)"%(status_constraint,additional_constraint)
    status=condorMonitor.CondorStatus("any",pool_name=factory_pool)
    status.require_integrity(True) #important, especially for proxy passing
    status.load(status_constraint)
    data=status.fetchStored()

    reserved_names=frontendConfig.condor_reserved_names
    for k in reserved_names:
        if data.has_key(k):
            del data[k]

    out={}
    # copy over requests and parameters
    for k in data.keys():
        kel=data[k].copy()
        el={"params":{},"monitor":{}}

        # first remove reserved anmes
        for attr in reserved_names:
            if kel.has_key(attr):
                del kel[attr]

        # then move the parameters and monitoring
        for (prefix,eldata) in ((frontendConfig.glidein_param_prefix,el["params"]), (frontendConfig.glidein_monitor_prefix,el["monitor"])):
            plen=len(prefix)
            for attr in kel.keys():
                if attr[:plen]==prefix:
                    eldata[attr[plen:]]=kel[attr]
                    del kel[attr]

        # what is left are glidein attributes
        el["attrs"]=kel

        out[k]=el

    return out
    

# can throw condorExe.ExeError
def findGlideins(factory_pool, factory_identity,
                 signtype,
                 additional_constraint=None,
                 have_proxy=False,
                 get_only_matching=True): # if this is false, return also glideins I cannot use
    global frontendConfig

    status_constraint = '(GlideinMyType=?="%s")' % frontendConfig.factory_id
    if not ((factory_identity == None) or (factory_identity == '*')): # identity checking can be disabled, if really wanted
        # filter based on AuthenticatedIdentity
        status_constraint += ' && (AuthenticatedIdentity=?="%s")' % factory_identity

    if signtype != None:
        status_constraint += ' && stringListMember("%s",%s)' % (signtype, frontendConfig.factory_signtype_id)

    if get_only_matching:
        if have_proxy:
            # must support secure message passing and must allow proxies
            status_constraint += '&& (PubKeyType=?="RSA") && (GlideinAllowx509_Proxy=!=False)'
        else:
            # cannot use factories that require a proxy
            status_constraint += '&& (GlideinRequirex509_Proxy=!=True)'

    if additional_constraint != None:
        status_constraint = "%s && (%s)" % (status_constraint, additional_constraint)
    status = condorMonitor.CondorStatus("any", pool_name=factory_pool)
    status.require_integrity(True) #important, especially for proxy passing

    status.load(status_constraint)

    data = status.fetchStored()

    reserved_names = frontendConfig.condor_reserved_names
    for k in reserved_names:
        if data.has_key(k):
            del data[k]

    out = {}

    # copy over requests and parameters
    for k in data.keys():
        kel = data[k].copy()

        el = {"params":{}, "monitor":{}}

        # first remove reserved anmes
        for attr in reserved_names:
            if kel.has_key(attr):
                del kel[attr]

        # then move the parameters and monitoring
        for (prefix, eldata) in ((frontendConfig.glidein_param_prefix, el["params"]),
                              (frontendConfig.glidein_monitor_prefix, el["monitor"])):
            plen = len(prefix)
            for attr in kel.keys():
                if attr[:plen] == prefix:
                    eldata[attr[plen:]] = kel[attr]
                    del kel[attr]

        # what is left are glidein attributes
        el["attrs"] = kel

        out[k] = el

    return out

def findGlideinClientMonitoring(factory_pool, my_name,
                                additional_constraint=None):
    global frontendConfig

    status_constraint = '(GlideinMyType=?="%s")' % frontendConfig.factoryclient_id
    if my_name != None:
        status_constraint = '%s && (ReqClientName=?="%s")' % my_name
    if additional_constraint != None:
        status_constraint = "%s && (%s)" % (status_constraint, additional_constraint)
    status = condorMonitor.CondorStatus("any", pool_name=factory_pool)
    status.load(status_constraint)

    data = status.fetchStored()

    reserved_names = frontendConfig.condor_reserved_names
    for k in reserved_names:
        if data.has_key(k):
            del data[k]

    out = {}

    # copy over requests and parameters
    for k in data.keys():
        kel = data[k].copy()

        el = {"params":{}, "monitor":{}}

        # first remove reserved anmes
        for attr in reserved_names:
            if kel.has_key(attr):
                del kel[attr]

        # then move the parameters and monitoring
        for (prefix, eldata) in ((frontendConfig.glidein_param_prefix, el["params"]),
                              (frontendConfig.glidein_monitor_prefix, el["monitor"])):
            plen = len(prefix)
            for attr in kel.keys():
                if attr[:plen] == prefix:
                    eldata[attr[plen:]] = kel[attr]
                    del kel[attr]

        # what is left are glidein attributes
        el["attrs"] = kel

        out[k] = el

    return out

############################################

class Credential:
    def __init__(self,proxy_id,proxy_fname,elementDescript):
        try:
            proxy_security_classes=elementDescript.merged_data['ProxySecurityClasses']
            proxy_trust_domains=elementDescript.merged_data['ProxyTrustDomains']
            proxy_types=elementDescript.merged_data['ProxyTypes']
            proxy_keyfiles=elementDescript.merged_data['ProxyKeyFiles']
            self.proxy_id=proxy_id
            self.filename=proxy_fname
            if proxy_types.has_key(proxy_fname):
                self.type=proxy_types[proxy_fname]
            else:
                self.type="Unknown"
            if proxy_security_classes.has_key(proxy_fname):
                    self.security_class=proxy_security_classes[proxy_fname]
            else:
                    self.security_class=proxy_id
            if proxy_trust_domains.has_key(proxy_fname):
                    self.trust_domain=proxy_trust_domains[proxy_fname]
            else:
                    self.trust_domain="None"

            # All others have a file to read
            if self.type!="username_password":
                proxy_fd=open(proxy_fname,'r')
                self.proxy_data=proxy_fd.read()
                proxy_fd.close()

            if self.type=="grid_proxy":
                pass
            if self.type=="grid_proxy+project_id":
                pass
            if self.type=="grid_proxy+voms_attr":
                pass
            ### Read second file for private key / password file
            if (self.type=="cert_pair")or (self.type=="key_pair") or (self.type=="username_password"):
                if proxy_keyfiles.has_key(proxy_fname):
                    self.key_fname=proxy_keyfiles[proxy_fname]
                    proxy_fd=open(self.key_fname,'r')
                    self.key_data=proxy_fd.read()
                    proxy_fd.close()
                
        except:
           logSupport.log.error("Could not read credential file '%s'"%proxy_fname)
           pass
    def file_id(self,filename):
        return str(abs(hash(filename))%100000)




class FrontendDescript:
    def __init__(self,
                 my_name,frontend_name,group_name,
                 web_url, main_descript, group_descript,
                 signtype, main_sign, group_sign,
                 x509_proxies_data=None):
        self.my_name=my_name
        self.frontend_name=frontend_name
        self.web_url=web_url
        self.main_descript=main_descript
        self.signtype=signtype
        self.main_sign=main_sign
        self.x509_proxies_data=x509_proxies_data
        self.group_name=group_name
        self.group_descript=group_descript
        self.group_sign=group_sign

    def need_encryption(self):
        return self.x509_proxies_data != None

    # return a list of strings
    def get_id_attrs(self):
        return ('ClientName = "%s"'%self.my_name,
                'FrontendName = "%s"'%self.frontend_name,
                'GroupName = "%s"'%self.group_name)

    def get_web_attrs(self):
        return ('WebURL = "%s"'%self.web_url,
                'WebSignType = "%s"'%self.signtype,
                'WebDescriptFile = "%s"'%self.main_descript,
                'WebDescriptSign = "%s"'%self.main_sign,
                'WebGroupURL = "%s"'%os.path.join(self.web_url,"group_%s"%self.group_name),
                'WebGroupDescriptFile = "%s"'%self.group_descript,
                'WebGroupDescriptSign = "%s"'%self.group_sign)


class FactoryKeys4Advertize:
    def __init__(self,
                 classad_identity,
                 factory_pub_key_id, factory_pub_key,
                 glidein_symKey=None): # if a symkey is not provided, or is not initialized, one will be generated
        self.classad_identity = classad_identity
        self.factory_pub_key_id = factory_pub_key_id
        self.factory_pub_key = factory_pub_key

        if glidein_symKey == None:
            glidein_symKey = symCrypto.SymAES256Key()
        if not glidein_symKey.is_valid():
            glidein_symKey = copy.deepcopy(glidein_symKey)
            glidein_symKey.new()
        self.glidein_symKey = glidein_symKey

    # returns a list of strings
    def get_key_attrs(self):
        glidein_symKey_str = self.glidein_symKey.get_code()
        return ('ReqPubKeyID = "%s"' % self.factory_pub_key_id,
                'ReqEncKeyCode = "%s"' % self.factory_pub_key.encrypt_hex(glidein_symKey_str),
                # this attribute will be checked against the AuthenticatedIdentity
                # this will prevent replay attacks, as only who knows the symkey can change this field
                # no other changes needed, as Condor provides integrity of the whole classAd
                'ReqEncIdentity = "%s"' % self.encrypt_hex(str(self.classad_identity)))

    def encrypt_hex(self, str):
        return self.glidein_symKey.encrypt_hex(str)

# class for creating FactoryKeys4Advertize objects
# will reuse the symkey as much as possible
class Key4AdvertizeBuilder:
    def __init__(self):
        self.keys_cache = {} # will contain a tuple of (key_obj,creation_time, last_access_time)

    def get_key_obj(self,
                    classad_identity,
                    factory_pub_key_id, factory_pub_key,
                    glidein_symKey=None): # will use one, if provided, but better to leave it blank and let the Builder create one
        # whoever can decrypt the pub key can anyhow get the symkey
        cache_id = factory_pub_key.get()

        if glidein_symKey != None:
            # when a key is explicitly given, cannot reuse a cached one
            key_obj = FactoryKeys4Advertize(classad_identity,
                                        factory_pub_key_id, factory_pub_key,
                                          glidein_symKey)
            # but I can use it for others
            if not self.keys_cache.has_key(cache_id):
                now = time.time()
                self.keys_cache[cache_id] = [key_obj, now, now]
            return key_obj
        else:
            if self.keys_cache.has_key(cache_id):
                self.keys_cache[cache_id][2] = time.time()
                return  self.keys_cache[cache_id][0]
            else:
                key_obj = FactoryKeys4Advertize(classad_identity,
                                              factory_pub_key_id, factory_pub_key,
                                             glidein_symKey=None)
                now = time.time()
                self.keys_cache[cache_id] = [key_obj, now, now]
                return key_obj

    # clear the cache
    def clear(self,
              created_after=None, # if not None, only clear entries older than this
              accessed_after=None): # if not None, only clear entries not accessed recently
        if (created_after == None) and (accessed_after == None):
            # just delete everything
            self.keys_cache = {}
            return

        for cache_id in self.keys_cache.keys():
            # if at least one criteria is not satisfied, delete the entry
            delete_entry = False

            if created_after != None:
                delete_entry = delete_entry or (self.keys_cache[cache_id][1] < created_after)

            if accessed_after != None:
                delete_entry = delete_entry or (self.keys_cache[cache_id][2] < accessed_after)

            if delete_entry:
                del self.keys_cache[cache_id]

#######################################
# INTERNAL, do not use directly

class AdvertizeParams:
    def __init__(self,
                 request_name, glidein_name,
                 min_nr_glideins, max_run_glideins,
                 glidein_params={}, glidein_monitors={},
                 glidein_params_to_encrypt=None, # params_to_encrypt needs key_obj
                 security_name=None, # needs key_obj
                 remove_excess_str=None):
        self.request_name = request_name
        self.glidein_name = glidein_name
        self.min_nr_glideins = min_nr_glideins
        self.max_run_glideins = max_run_glideins
        if remove_excess_str == None:
            remove_excess_str = "NO"
        elif not (remove_excess_str in ("NO", "WAIT", "IDLE", "ALL", "UNREG")):
            raise RuntimeError, 'Invalid remove_excess_str(%s), valid values are "NO","WAIT","IDLE","ALL","UNREG"' % remove_excess_str
        self.remove_excess_str = remove_excess_str
        self.glidein_params = glidein_params
        self.glidein_monitors = glidein_monitors
        self.glidein_params_to_encrypt = glidein_params_to_encrypt
        self.security_name = security_name



# Given a file, advertize
# Can throw a CondorExe/ExeError exception
def advertizeWorkFromFile(factory_pool,
                          fname,
                          remove_file=True,
                          is_multi=False):
    try:
        exe_condor_advertise(fname, "UPDATE_MASTER_AD", factory_pool, is_multi=is_multi)
    finally:
        if remove_file:
            os.remove(fname)



# END INTERNAL
########################################


class MultiAdvertizeWork:
    def __init__(self,
                 descript_obj):        # must be of type FrontendDescript
        self.descript_obj=descript_obj
        self.factory_queue={}          # will have a queue x factory, each element is list of tuples (params_obj, key_obj)
        self.global_pool=[]
        self.global_key={}
        self.global_params={}
        self.factory_constraint={}

    # add a request to the list
    def add(self,
            factory_pool,
            request_name,glidein_name,
            min_nr_glideins,max_run_glideins,
            glidein_params={},glidein_monitors={},
            key_obj=None,                     # must be of type FactoryKeys4Advertize
            glidein_params_to_encrypt=None,   # params_to_encrypt needs key_obj
            security_name=None,               # needs key_obj
            remove_excess_str=None,
            trust_domain="Any",
            auth_method="Any"):

        params_obj=AdvertizeParams(request_name,glidein_name,
                                   min_nr_glideins,max_run_glideins,
                                   glidein_params,glidein_monitors,
                                   glidein_params_to_encrypt,security_name,
                                   remove_excess_str)
        if not self.factory_queue.has_key(factory_pool):
            self.factory_queue[factory_pool] = []
        self.factory_queue[factory_pool].append((params_obj, key_obj))
        self.factory_constraint[params_obj.request_name]=(trust_domain, auth_method)

    def add_global(self,factory_pool,request_name,security_name,key_obj):
        self.global_pool.append(factory_pool)
        self.global_key[factory_pool]=key_obj
        self.global_params[factory_pool]=(request_name,security_name)

    # retirn the queue depth
    def get_queue_len(self):
        count = 0
        for factory_pool in self.factory_queue.keys():
            count += len(self.factory_queue[factory_pool])
        return count

    def do_global_advertize(self):
        """
        Advertize globals with credentials
        """
        for factory_pool in self.global_pool:
            short_time = time.time()-1.05e9
            tmpname="/tmp/globaliad_%li_%li"%(short_time,os.getpid())
            glidein_params_to_encrypt={}
            fd=file(tmpname,"w")
            if self.descript_obj.x509_proxies_data!=None:
                nr_credentials=len(self.descript_obj.x509_proxies_data)
                glidein_params_to_encrypt['NumberOfCredentials']="%s"%nr_credentials
            else:
                nr_credentials=0
            request_name="Global"
            if (factory_pool in self.global_params):
                request_name,security_name=self.global_params[factory_pool]
                glidein_params_to_encrypt['SecurityName']=security_name
            classad_name="%s@%s"%(request_name,self.descript_obj.my_name)
            fd.write('MyType = "%s"\n'%frontendConfig.client_global)
            fd.write('GlideinMyType = "%s"\n'%frontendConfig.client_global)
            fd.write('GlideinWMSVersion = "%s"\n'%frontendConfig.glideinwms_version)
            fd.write('Name = "%s"\n'%classad_name)
            fd.write('FrontendName = "%s"\n'%self.descript_obj.frontend_name)
            fd.write('GroupName = "%s"\n'%self.descript_obj.group_name)
            fd.write('ClientName = "%s"\n'%self.descript_obj.my_name)
            for i in range(nr_credentials):
                cred_el=self.descript_obj.x509_proxies_data[i]
                if (hasattr(cred_el,'filename')):
                    data_fd=open(cred_el.filename)
                    cred_data=data_fd.read()
                    data_fd.close()
                    glidein_params_to_encrypt[cred_el.file_id(cred_el.filename)]=cred_data
                    if (hasattr(cred_el,'security_class')):
                        # Convert the sec class to a string so the Factory can interpret the value correctly
                        glidein_params_to_encrypt["SecurityClass"+cred_el.file_id(cred_el.filename)]=str(cred_el.security_class)
                if (hasattr(cred_el,'key_fname')):
                    data_fd=open(cred_el.key_fname)
                    cred_data=data_fd.read()
                    data_fd.close()
                    glidein_params_to_encrypt[cred_el.file_id(cred_el.key_fname)]=cred_data
                    if (hasattr(cred_el,'security_class')):
                        # Convert the sec class to a string so the Factory can interpret the value correctly
                        glidein_params_to_encrypt["SecurityClass"+cred_el.file_id(cred_el.key_fname)]=str(cred_el.security_class)
            if (factory_pool in self.global_key):
                key_obj=self.global_key[factory_pool]
            if key_obj!=None:
                fd.write(string.join(key_obj.get_key_attrs(),'\n')+"\n")
                for attr in glidein_params_to_encrypt.keys():
                    #logSupport.log.debug("Encrypting (%s,%s)"%(attr,glidein_params_to_encrypt[attr]))
                    el = key_obj.encrypt_hex(glidein_params_to_encrypt[attr])
                    escaped_el = string.replace(string.replace(str(el), '"', '\\"'), '\n', '\\n')
                    fd.write('%s%s = "%s"\n' % (frontendConfig.encrypted_param_prefix, attr, escaped_el))
 
            fd.close()
            advertizeWorkFromFile(factory_pool, tmpname, remove_file=True)

    def do_advertize(self):
        """
        Do the actual advertizing
        Can throw MultiExeError
        """
        error_arr=[]

        # get a 9 digit number that will stay 9 digit for the next 25 years
        short_time = time.time() - 1.05e9
        idx = 0
        for factory_pool in self.factory_queue.keys():
            idx = idx + 1
            self.unique_id=1
            self.adname = "/tmp/gfi_aw_%li_%li_%li" % (short_time, os.getpid(), idx)

            # this should be done in parallel, but keep it serial for now
            try:
                append_flag=False
                error_arr=[]
                filename_arr=[]
                if (frontendConfig.advertise_use_multi==True):
                    filename_arr.append(self.adname)
                for el in self.factory_queue[factory_pool]:
                    params_obj, key_obj = el
                    filename_arr_el=self.createAdvertizeWorkFile(factory_pool,params_obj,key_obj)
                    for f in filename_arr_el:
                        filename_arr.append(f)
                
                # Advertize all the files (if multi, should only be one) 
                for filename in filename_arr:
                    advertizeWorkFromFile(factory_pool, filename, remove_file=True, is_multi=frontendConfig.advertise_use_multi)

                if len(error_arr)>0:
                    raise MultiExeError, error_arr

            except condorExe.ExeError, e:
                error_arr.append(e)
        self.factory_queue = {} # clean queue

        if len(error_arr) > 0:
            raise MultiExeError, error_arr


    def createAdvertizeWorkFile(self, factory_pool, params_obj, key_obj=None):
        global frontendConfig
        descript_obj=self.descript_obj

        if descript_obj.x509_proxies_data!=None:
            nr_credentials=len(descript_obj.x509_proxies_data)
        else:
            nr_credentials=1
        cred_filename_arr=[]
        for i in range(nr_credentials):
            fd=None
            try:
                encrypted_params={} # none by default
                glidein_params_to_encrypt=params_obj.glidein_params_to_encrypt
                if glidein_params_to_encrypt==None:
                    glidein_params_to_encrypt={}
                else:
                    glidein_params_to_encrypt=copy.deepcopy(glidein_params_to_encrypt)
                classad_name="%s@%s"%(params_obj.request_name,descript_obj.my_name)
                
                if descript_obj.x509_proxies_data!=None:
                    credential_el=descript_obj.x509_proxies_data[i]
                    if (params_obj.request_name in self.factory_constraint):
                        factory_trust,factory_auth=self.factory_constraint[params_obj.request_name]
                        if (credential_el.type!=factory_auth) and (factory_auth!="Any"):
                            logSupport.log.debug("Credential %s does not match auth method %s (for %s), skipping..."%(credential_el.type,factory_auth,params_obj.request_name))
                            continue
                        if (credential_el.trust_domain!=factory_trust) and (factory_trust!="Any"):
                            logSupport.log.debug("Credential %s does not match %s (for %s) domain, skipping..."%(credential_el.trust_domain,factory_trust,params_obj.request_name))
                            continue
                    # Convert the sec class to a string so the Factory can interpret the value correctly
                    glidein_params_to_encrypt['SecurityClass']=str(credential_el.security_class)
                    classad_name=credential_el.file_id(credential_el.filename)+"_"+classad_name
                    if (credential_el.type.startswith("username_password")):
                        glidein_params_to_encrypt['Username']=credential_el.file_id(credential_el.filename);
                        glidein_params_to_encrypt['Password']=credential_el.file_id(credential_el.key_fname);
                    if (credential_el.type.startswith("grid_proxy")):
                        glidein_params_to_encrypt['SubmitProxy']=credential_el.file_id(credential_el.filename);
                    if (credential_el.type.startswith("cert_pair")):
                        glidein_params_to_encrypt['PublicCert']=credential_el.file_id(credential_el.filename);
                        glidein_params_to_encrypt['PrivateCert']=credential_el.file_id(credential_el.key_fname);
                    if (credential_el.type.startswith("key_pair")):
                        glidein_params_to_encrypt['PublicKey']=credential_el.file_id(credential_el.filename);
                        glidein_params_to_encrypt['PrivateKey']=credential_el.file_id(credential_el.key_fname);
                
                if (frontendConfig.advertise_use_multi==True):
                    fname=self.adname
                else:
                    fname=self.adname+"_"+str(self.unique_id)
                    self.unique_id=self.unique_id+1
                    cred_filename_arr.append(fname)
                logSupport.log.debug("Writing %s"%fname)
                fd = file(fname, "a")
            
                fd.write('MyType = "%s"\n'%frontendConfig.client_id)
                fd.write('GlideinMyType = "%s"\n'%frontendConfig.client_id)
                fd.write('GlideinWMSVersion = "%s"\n'%frontendConfig.glideinwms_version)
                fd.write('Name = "%s"\n'%classad_name)
                fd.write(string.join(descript_obj.get_id_attrs(),'\n')+"\n")
                fd.write('ReqName = "%s"\n'%params_obj.request_name)
                fd.write('ReqGlidein = "%s"\n'%params_obj.glidein_name)

                fd.write(string.join(descript_obj.get_web_attrs(),'\n')+"\n")

                if key_obj!=None:
                    fd.write(string.join(key_obj.get_key_attrs(),'\n')+"\n")
                    if params_obj.security_name!=None:
                        glidein_params_to_encrypt['SecurityName']=params_obj.security_name
                    for attr in glidein_params_to_encrypt.keys():
                        encrypted_params[attr]=key_obj.encrypt_hex(glidein_params_to_encrypt["%s"%attr])
                    
                fd.write('ReqIdleGlideins = %i\n'%params_obj.min_nr_glideins)
                fd.write('ReqMaxRunningGlideins = %i\n'%params_obj.max_run_glideins)
                fd.write('ReqRemoveExcess = "%s"\n'%params_obj.remove_excess_str)
                         
                # write out both the params and monitors
                for (prefix, data) in ((frontendConfig.glidein_param_prefix, params_obj.glidein_params),
                                  (frontendConfig.glidein_monitor_prefix, params_obj.glidein_monitors),
                                  (frontendConfig.encrypted_param_prefix, encrypted_params)):
                    for attr in data.keys():
                        el = data[attr]
                        if type(el) == type(1):
                            # don't quote ints
                            fd.write('%s%s = %s\n' % (prefix, attr, el))
                        else:
                            escaped_el = string.replace(string.replace(str(el), '"', '\\"'), '\n', '\\n')
                            fd.write('%s%s = "%s"\n' % (prefix, attr, escaped_el))
                # add a final empty line... useful when appending
                fd.write('\n')
                fd.close()
            except:
                logSupport.log.debug("Exception writing advertisement file")
                # remove file in case of problems
                if (fd!=None):
                    fd.close()
                    os.remove(fname)
                raise
        return cred_filename_arr



# Remove ClassAd from Collector
def deadvertizeWork(factory_pool,
                    my_name, request_name):
    global frontendConfig

    # get a 9 digit number that will stay 9 digit for the next 25 years
    short_time = time.time() - 1.05e9
    tmpnam = "/tmp/gfi_aw_%li_%li" % (short_time, os.getpid())
    fd = file(tmpnam, "w")
    try:
        try:
            fd.write('MyType = "Query"\n')
            fd.write('TargetType = "%s"\n' % frontendConfig.client_id)
            fd.write('Requirements = Name == "%s@%s"\n' % (request_name, my_name))
        finally:
            fd.close()

        exe_condor_advertise(tmpnam, "INVALIDATE_MASTER_ADS", factory_pool)
    finally:
        os.remove(tmpnam)

# Remove ClassAd from Collector
def deadvertizeAllWork(factory_pool,
                       my_name):
    global frontendConfig

    # get a 9 digit number that will stay 9 digit for the next 25 years
    short_time = time.time() - 1.05e9
    tmpnam = "/tmp/gfi_aw_%li_%li" % (short_time, os.getpid())
    fd = file(tmpnam, "w")
    try:
        try:
            fd.write('MyType = "Query"\n')
            fd.write('TargetType = "%s"\n' % frontendConfig.client_id)
            fd.write('Requirements = ClientName == "%s"\n' % my_name)
        finally:
            fd.close()

        exe_condor_advertise(tmpnam, "INVALIDATE_MASTER_ADS", factory_pool)
    finally:
        os.remove(tmpnam)


###############################################################################
# Code to advertise resource classads to the User Pool
###############################################################################

class Classad:
    """
    Base class describing a classad.
    """
    
    def __init__(self, type, advertiseCmd, invalidateCmd):
        """
        Constructor

        @type type: string 
        @param type: Type of the classad
        @type advertiseCmd: string 
        @param advertiseCmd: Condor update-command to advertise this classad 
        @type invalidateCmd: string 
        @param invalidateCmd: Condor update-command to invalidate this classad 
        """
        
        global frontendConfig

        self.adType = type
        self.adAdvertiseCmd = advertiseCmd
        self.adInvalidateCmd = invalidateCmd
        
        self.adParams = {}
        self.adParams['MyType'] = self.adType
        self.adParams['GlideinMyType'] = self.adType
        self.adParams['GlideinWMSVersion'] = frontendConfig.glideinwms_version

    def __str__(self):
        """
        String representation of the classad.
        """
        
        ad = ""
        for param in self.adParams.keys():
            if isinstance(self.adParams[param], str):
                ad += '%s = "%s"\n' % (param, self.adParams[param])
            elif isinstance(self.adParams[param], unicode):
                ad += '%s = "%s"\n' % (param, self.adParams[param])
            else:
                ad += '%s = %s\n' % (param, self.adParams[param])  
        return ad


class ResourceClassad(Classad):
    """
    This class describes the resource classad. Frontend advertises the 
    resource classad to the user pool as an UPDATE_AD_GENERIC type classad
    """
    
    def __init__(self, factory_ref, frontend_ref):
        """
        Class Constructor

        @type factory_ref: string 
        @param factory_ref: Name of the resource in the glidefactory classad
        @type frontend_ref: string 
        @param type: Name of the resource in the glideclient classad
        """

        Classad.__init__(self, 'glideresource', 'UPDATE_AD_GENERIC',
                         'INVALIDATE_ADS_GENERIC')
        
        self.adParams['GlideFactoryName'] = "%s" % factory_ref
        self.adParams['GlideClientName'] = "%s" % frontend_ref
        self.adParams['Name'] = "%s@%s" % (factory_ref, frontend_ref)
        self.adParams['GLIDEIN_In_Downtime'] = 'False'
       
    def setInDownTime(self, downtime):
        """
        Set the downtime flag for the resource in the classad

        @type downtime: bool
        @param downtime: True if the entry is in down time.
        """
        self.adParams['GLIDEIN_In_Downtime'] = str(downtime)


    def setGlideClientMonitorInfo(self, monitorInfo):
        """
        Set the GlideClientMonitor* for the resource in the classad
        
        @type monitorInfo: list 
        @param monitorInfo: GlideClientMonitor information.
        """
        if len(monitorInfo) == 13:
            self.adParams['GlideClientMonitorJobsIdle'] = monitorInfo[0]
            self.adParams['GlideClientMonitorJobsIdleMatching'] = monitorInfo[1]
            self.adParams['GlideClientMonitorJobsIdleEffective'] = monitorInfo[2]
            self.adParams['GlideClientMonitorJobsIdleOld'] = monitorInfo[3]
            self.adParams['GlideClientMonitorJobsIdleUnique'] = monitorInfo[4]
            self.adParams['GlideClientMonitorJobsRunning'] = monitorInfo[5]
            self.adParams['GlideClientMonitorJobsRunningHere'] = monitorInfo[6]
            self.adParams['GlideClientMonitorJobsRunningMax'] = monitorInfo[7]
            self.adParams['GlideClientMonitorGlideinsTotal'] = monitorInfo[8]
            self.adParams['GlideClientMonitorGlideinsIdle'] = monitorInfo[9]
            self.adParams['GlideClientMonitorGlideinsRunning'] = monitorInfo[10]
            self.adParams['GlideClientMonitorGlideinsRequestIdle'] = monitorInfo[11]
            self.adParams['GlideClientMonitorGlideinsRequestMaxRun'] = monitorInfo[12]
        else:
            raise RuntimeError, 'Glide client monitoring structure changed. Resource ad may have incorrect GlideClientMonitor values'
    

    def setEntryInfo(self, info):
        """
        Set the useful entry specific info for the resource in the classad

        @type info: dict 
        @param info: Useful info from the glidefactory classad  
        """
        
        eliminate_attrs = Set([
                 'CurrentTime', 'USE_CCB', 'PubKeyValue', 'PubKeyType',
                 'AuthenticatedIdentity', 'GlideinName', 'FactoryName', 
                 'EntryName', 'GlideinWMSVersion', 'PubKeyObj', 
                 'LastHeardFrom', 'PubKeyID', 'SupportedSignTypes',
                 'GLIDEIN_In_Downtime'
                ])
        available_attrs = Set(info.keys())
        publish_attrs = available_attrs - eliminate_attrs
        for attr in publish_attrs:
            self.adParams[attr] = info[attr]

    
    def setGlideFactoryMonitorInfo(self, info):
        """
        Set the GlideinFactoryMonitor* for the resource in the classad

        @type info: string 
        @param info: Useful information from the glidefactoryclient classad
        """
        
        # Required keys do not start with TotalClientMonitor but only
        # start with Total. Substitute Total with GlideFactoryMonitor
        # and put it in the classad
        
        for key in info.keys():
            if not key.startswith('TotalClientMonitor'):
                if key.startswith('Total'):
                    ad_key = key.replace('Total', 'GlideFactoryMonitor', 1)
                    self.adParams[ad_key] = info[key]
    
    
class ResourceClassadAdvertiser:
    """
    Class to handle the advertisement of resource classads to the user pool
    """


    def __init__(self, pool=None, multi_support=False):
        """
        Constructor

        @type pool: string 
        @param pool: Collector address
        @type multi_support: bool 
        @param multi_support: True if the installation support advertising multiple classads with one condor_advertise command. Defaults to False.
        """
        
        # Dictionary of classad objects
        self.classads = {}
        self.pool = pool
        self.multiAdvertiseSupport = multi_support
        self.adType = 'glideresource'
        self.adAdvertiseCmd = 'UPDATE_AD_GENERIC'
        self.adInvalidateCmd = 'INVALIDATE_ADS_GENERIC'
        self.multiClassadDelimiter = '\n'


    def addClassad(self, name, ad_obj):
        """
        Adds the classad to the classad dictionary
        
        @type name: string 
        @param name: Name of the classad
        @type ad_obj: ClassAd
        @param ad_obj: Actual classad object
        """

        self.classads[name] = ad_obj
    

    def classadToFile(self, ad):
        """
        Write classad to the file and return the filename
        
        @type ad: string 
        @param ad: Name of the classad
        
        @rtype: string
        @return: Name of the file
        """
        
        # get a 9 digit number that will stay 9 digit for next 25 years
        short_time = time.time() - 1.05e9
        fname = "/tmp/gfi_ar_%li_%li" % (short_time, os.getpid())
        try:
            fd = file(fname, "w")
        except:
            return ""
        
        try:
            fd.write("%s" % self.classads[ad])
        finally:
            fd.close()
        
        return fname


    def classadsToFile(self, ads):
        """
        Write multiple classads to a file and return the filename. 
        Use only when multi advertise is supported by condor.
        
        @type ads: list
        @param ads: Classad names
        
        @rtype: string
        @return: Filename containing all the classads to advertise
        """
        
        # get a 9 digit number that will stay 9 digit for next 25 years
        short_time = time.time() - 1.05e9
        fname = "/tmp/gfi_ar_%li_%li" % (short_time, os.getpid())
        
        try:
            fd = file(fname, "w")
        except:
            return ""
        
        try:
            for ad in ads:
                fd.write('%s' % self.classads[ad])
                # Append an empty line for advertising multiple classads
                fd.write(self.multiClassadDelimiter)
        finally:
            fd.close()
        
        return fname


    def doAdvertise(self, fname):
        """
        Do the actual advertisement of classad(s) in the file

        @type fname: string
        @param fname: File name containing classad(s)
        """

        if (fname) and (fname != ""):
            try:
                exe_condor_advertise(fname, self.adAdvertiseCmd,
                                     self.pool,
                                     is_multi=self.multiAdvertiseSupport)
            finally:
                os.remove(fname)
        else:
            raise RuntimeError, 'Failed advertising %s classads' % self.adType

    def advertiseClassads(self, ads=None):
        """
        Advertise multiple classads to the pool

        @type ads: list
        @param ads: classad names to advertise
        """

        if (ads == None) or (len(ads) == 0) :
            return

        if self.multiAdvertiseSupport:
            fname = self.classadsToFile(ads)
            self.doAdvertise(fname)
        else:
            for ad in ads:
                self.advertiseClassad(ad)

    
    def advertiseClassad(self, ad):
        """
        Advertise the classad to the pool
        
        @type ad: string 
        @param ad: Name of the classad
        """

        fname = self.classadToFile(ad)
        self.doAdvertise(fname)
    
    
    def advertiseAllClassads(self):
        """
        Advertise all the known classads to the pool
        """
        
        self.advertiseClassads(self.classads.keys())
    
    
    def invalidateClassad(self, ad):
        """
        Invalidate the classad from the pool
        
        @type type: string 
        @param type: Name of the classad
        """

        global frontendConfig
    
        # get a 9 digit number that will stay 9 digit for next 25 years
        short_time = time.time() - 1.05e9
        tmpnam = "/tmp/gfi_ar_%li_%li" % (short_time, os.getpid())
        fd = file(tmpnam,"w")
        try:
            try:
                fd.write('MyType = "Query"\n')
                fd.write('TargetType = "%s"\n' % self.classads[ad].adType)
                fd.write('Requirements = Name == "%s"\n' % ad)
            finally:
                fd.close()
    
            exe_condor_advertise(tmpnam, self.classads[ad].adInvalidateCmd, 
                                 self.pool,
                                 is_multi=self.multiAdvertiseSupport)
        finally:
            os.remove(tmpnam)

    
    def invalidateAllClassads(self):
        """
        Invalidate all the known classads
        """

        for ad in self.classads.keys():
            self.invalidateClassad(ad)


    def invalidateConstrainedClassads(self, constraint):
        """
        Invalidate classads from the pool matching the given constraints
        
        @type type: string 
        @param type: Condor constraints for filtering the classads
        """

        global frontendConfig
    
        # get a 9 digit number that will stay 9 digit for next 25 years
        short_time = time.time() - 1.05e9
        tmpnam = "/tmp/gfi_ar_%li_%li" % (short_time, os.getpid())
        fd = file(tmpnam,"w")
        try:
            try:
                fd.write('MyType = "Query"\n')
                fd.write('TargetType = "%s"\n' % self.adType)
                fd.write('Requirements = %s' % constraint)
            finally:
                fd.close()
    
            exe_condor_advertise(tmpnam, self.adInvalidateCmd, 
                                 self.pool,
                                 is_multi=self.multiAdvertiseSupport)
        finally:
            os.remove(tmpnam)

        
    def getAllClassads(self):
        """
        Return all the known classads
        
        @rtype: string
        @return: All the known classads delimited by empty line 
        """

        ads = ""
        
        for ad in self.classads.keys():
            ads = "%s%s\n" % (ads, self.classads[ad]) 
        return ads

############################################################
#
# I N T E R N A L - Do not use
#
############################################################

def exe_condor_advertise(fname,command, pool, is_multi=False):
    logSupport.log.debug("CONDOR ADVERTISE %s %s %s %s" % (fname, command,
                                                           pool, is_multi))
    return condorManager.condorAdvertise(fname, command, 
                                         frontendConfig.advertise_use_tcp,
                                         is_multi, pool)

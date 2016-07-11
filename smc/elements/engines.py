from abc import ABCMeta, abstractmethod
from smc.elements.element import SMCElement
from smc.elements.interfaces import inline_intf, l2_mgmt_interface, \
    l3_mgmt_interface, l3_interface, inline_interface, capture_interface
import smc.actions.search as search
import smc.api.common as common_api
from smc.api.web import SMCException
from smc.elements.system import SystemInfo

class Engine(object):
    """
    Top level engine class representing settings of the generic engine, independent of
    the engine type. The load method is required to initialize this class properly and 
    is abstract so must be called from a subclass,
    either Node or the direct engine types:
    
    :class:`smc.elements.engines.Layer3Firewall`
    
    :class:`smc.elements.engines.Layer2Firewall`
    
    :class:`smc.elements.engines.IPS`
    
    This is intended to store the top level engine properties and operations specific to 
    the engine.
    
    :class:`smc.elements.engines.Node` class will store information specific to the individual
    node itself such as rebooting, going online/offline, change user pwd, ssh pwd reset, etc. 
    """
    
    __metaclass__ = ABCMeta
    
    def __init__(self, name):
        self.name = name
        self.href = None #pulled from self
        self.etag = None #saved in case of modifications
        self.engine_version = None
        self.log_server_ref = None
        self.cluster_mode = None
        self.domain_server_address = []
        self.engine_json = None
        self.engine_links = [] #links specific to engine level
    
    @abstractmethod    
    def load(self):
        engine = search.element_as_json_with_etag(self.name)
        if engine:
            self.engine_json = engine.json
            self.etag = engine.etag
            self.engine_links.extend(engine.json.get('link'))
            self.domain_server_address.extend(engine.json.get('domain_server_address'))
            self.engine_version = engine.json.get('engine_version')
            self.log_server_ref = engine.json.get('log_server_ref')
            self.cluster_mode = engine.json.get('cluster_mode')
            self.href = self.__load_href('self') #get self href
            return self
        else:
            raise SMCException("Cannot load engine name: %s, please ensure the name is correct"
                               " and the engine exists." % self.name)
    
    @classmethod
    @abstractmethod
    def create(cls):
        engine = {
                "name": cls.name,
                "nodes": [],
                "domain_server_address": [],
                "log_server_ref": cls.log_server_ref,
                "physicalInterfaces": []
                }
        node =  {
                cls.node_type: {
                    "activate_test": True,
                    "disabled": False,
                    "loopback_node_dedicated_interface": [],
                    "name": cls.name + " node 1",
                    "nodeid": 1
                    }
                }
        if cls.domain_server_address:
            rank_i = 0
            for entry in cls.domain_server_address:
                engine.get('domain_server_address').append(
                                            {"rank": rank_i, "value": entry})
        engine.get('nodes').append(node)
        cls.engine_json = engine
        return cls
    
    def refresh(self, wait_for_finish=True, sleep_interval=3):
        """ 
        Refresh existing policy on specified device. This is an asynchronous 
        call that will return a 'follower' link that can be queried to determine 
        the status of the task. 
        
        See :func:`async_handler` for more information on how to obtain results
        
        :method: POST
        :param wait_for_finish: whether to wait in a loop until the upload completes
        :param sleep_interval: length of time to sleep between progress checks (secs)
        :return: follower href if wait_for_finish=False, else result href on last yield
        """
        element = self._element('refresh')
        return async_handler(element, wait_for_finish, sleep_interval)
    
    def upload(self, policy=None, wait_for_finish=True, sleep_interval=3):
        """ Upload policy to existing engine. If no policy is specified, and the engine
        has already had a policy installed, this policy will be re-uploaded. 
        
        This is typically used to install a new policy on the engine. If you just
        want to re-push an existing policy, call :func:`refresh`
        
        :param policy: name of policy to upload to engine
        :param wait_for_finish: whether to wait for async responses
        :param sleep_interval: how long to wait between async responses
        """
        if not policy: #if policy not specified SMC seems to apply some random policy: bug?
            policy = self.status().get('installed_policy')
            
        element = self._element('upload')
        element.params = {'filter': policy}
        return async_handler(element, wait_for_finish, sleep_interval)
    
    def node(self):
        """ Return node/s references for this engine. For a cluster this will
        contain multiple entries. 
        
        :method: GET
        :return: dict list with reference {href, name, type}
        """
        return search.element_by_href_as_json(self.__load_href('nodes')) 
   
    def interface(self):
        """ Get all interfaces, including non-physical interfaces such
        as tunnel or capture interfaces.
        
        :method: GET
        :return: list of dict entries with href,name,type, or None
        """
        return search.element_by_href_as_json(self.__load_href('interfaces')) 
    
    def generate_snapshot(self, filename='snapshot.xml'):
        """ Generate and retrieve a policy snapshot from the engine
        This is blocking as file is downloaded
        
        :method: GET
        :param filename: name of file to save file to, including directory path
        :return: None
        """
        element = self._element('generate_snapshot')
        element.stream = True
        element.filename = filename
        return common_api.fetch_content_as_file(element)

    def add_route(self, gateway, network):
        """ Add a route to engine. Specify gateway and network. 
        If this is the default gateway, use a network address of
        0.0.0.0/0.
        
        .. note: This will fail if the gateway provided does not have a 
        corresponding interface on the network.
        
        :method: POST
        :param gateway: gateway of an existing interface
        :param network: network address in cidr format
        """
        element = self._element('add_route')
        element.params = {'gateway': gateway, 'network': network}
        return common_api.create(element)

    def blacklist_add(self, src, dst, duration=3600):
        """ Add blacklist entry to engine node by name
    
        :method: POST
        :param name: name of engine node or cluster
        :param src: source to blacklist, can be /32 or network cidr
        :param dst: dest to deny to, 0.0.0.0/32 indicates all destinations
        :param duration: how long to blacklist in seconds
        :return: href, or None
        """
        bl = { "name": "",
              "duration": duration,
              "end_point1": { 
                             "name": "", 
                             "address_mode": 
                             "address", 
                             "ip_network": src },
              "end_point2": { 
                             "name": 
                             "", 
                             "address_mode": 
                             "address", 
                             "ip_network": dst }
              }
        element = self._element('blacklist')
        element.json = bl
        return common_api.create(element)       
    
    def blacklist_flush(self):
        """ Flush entire blacklist for node name
    
        :method: DELETE
        :param name: name of node or cluster to remove blacklist
        :return: None, or message if failure
        """
        element = self._element('flush_blacklist')
        return common_api.delete(element) 
    
    def alias_resolving(self):
        """ Alias definitions defined for this engine 
        Aliases can be used in rules to simplify multiple object creation
        
        :method: GET
        :return: dict list of aliases and their values
        """
        return search.element_by_href_as_json(self.__load_href('alias_resolving'))
       
    def routing_monitoring(self):
        """ Return route information for the engine, including gateway, networks
        and type of route (dynamic, static)
        
        :method: GET
        :return: dict of dict list entries representing routes
        """
        return search.element_by_href_as_json(self.__load_href('routing_monitoring'))
    
    def export(self, wait_for_finish=True, sleep_interval=3,
               filename='export.xml'): 
        """ Generate export on engine. Once the export is complete, 
        a result href is returned.  
        
        :mathod: POST
        :param wait_for_finish: whether to wait for task to finish
        :param sleep_interval: length of time between async messages
        :param filename: if set, the export will download the file. 
        :return: href of export
        """
        element = self._element('export')
        element.params = {'filter': self.name}
        #wait for the export to be complete, fetch result export by href
        for msg in async_handler(element, display_msg=False):
            element.href = msg
        if element.href:
            element.stream = True
            element.filename = filename
        return common_api.fetch_content_as_file(element)
    
    def internal_gateway(self):
        """ Engine level VPN gateway reference
        
        :method: GET
        :return: dict list of internal gateway references
        """
        return search.element_by_href_as_json(self.__load_href('internal_gateway'))
        
    def routing(self):
        """ Retrieve routing json from engine node
        
        :method: GET
        :return: json representing routing configuration
        """
        return search.element_by_href_as_json(self.__load_href('routing'))
    
    def antispoofing(self):
        """ Antispoofing interface information. By default is based on routing
        but can be modified in special cases
        
        :method: GET
        :return: dict of antispoofing settings per interface
        """
        return search.element_by_href_as_json(self.__load_href('antispoofing'))
    
    def snapshot(self):
        """ References to policy based snapshots for this engine, including
        the date the snapshot was made
        
        :method: GET
        :return: dict list with {href,name,type}
        """
        return search.element_by_href_as_json(self.__load_href('snapshots'))
               
    def physical_interface(self):
        """ Get only physical interfaces for this engine node. This will not include
        tunnel interfaces or capture interfaces.
       
        :method: GET
        :return: list of dict entries with href,name,type, or None
        """
        return search.element_by_href_as_json(self.__load_href('physical_interface')) 
    
    def physical_interface_add(self, ip, ip_network, int_id):
        """ Add physical interface
        
        :param ip: ipaddress of interface
        :param ip_network: network address in cidr
        :param int_id: id of interface
        :return: href of interface, or None
        """
        interface = l3_interface(ip, ip_network, int_id)
        element = self._element('physical_interface')
        element.json = interface.get('physical_interface')
        return common_api.create(element)
    
    def physical_interface_del(self, name):
        """ Delete physical interface by name
        To retrieve name, use :func:`physical_interface` to
        list all configured interfaces for this engine
        
        :param name: name of interface (typically 'Interface <num>'
        :return
        """
        href = [interface.get('href')
                for interface in self.interface()
                if interface.get('name') == name]
        if href:
            element = SMCElement.factory(href=href.pop())
            return common_api.delete(element)
    
    def inline_interface_add(self, int_id, 
                             logical_int='default_eth'):
        inline = inline_interface(interface_id=int_id,
                                  logical_interface_ref=logical_int)
        element = self._element('physical_interface')
        element.json = inline.get('physical_interface')
        return common_api.create(element)
    
    def capture_interface_add(self, int_id, logical_int):
        capture = capture_interface(interface_id=int_id,
                                    logical_interface_ref=logical_int)
        element = self._element('physical_interface')
        element.json = capture.get('physical_interface')
        return common_api.create(element)
          
    def tunnel_interface(self):
        """ Get only tunnel interfaces for this engine node.
        
        :method: GET
        :return: list of dict entries with href,name,type, or None
        """
        return search.element_by_href_as_json(self.__load_href('tunnel_interface')) 
    
    def modem_interface(self):
        """ Get only modem interfaces for this engine node.
        
        :method: GET
        :return: list of dict entries with href,name,type, or None
        """
        return search.element_by_href_as_json(self.__load_href('modem_interface'))
    
    def adsl_interface(self):
        """ Get only adsl interfaces for this engine node.
        
        :method: GET
        :return: list of dict entries with href,name,type, or None
        """
        return search.element_by_href_as_json(self.__load_href('adsl_interface'))
    
    def wireless_interface(self):
        """ Get only wireless interfaces for this engine node.
        
        :method: GET
        :return: list of dict entries with href,name,type, or None
        """
        return search.element_by_href_as_json(self.__load_href('wireless_interface'))
    
    def switch_physical_interface(self):
        """ Get only switch physical interfaces for this engine node.
        
        :method: GET
        :return: list of dict entries with href,name,type, or None
        """
        return search.element_by_href_as_json(self.__load_href('switch_physical_interface'))
    
    def __load_href(self, action):
        """ Pull the direct href from engine link list cache """
        href = [entry.get('href') for entry in self.engine_links \
                if entry.get('rel') == action]      
        if href:
            return href.pop()
    
    def _element(self, link):
        """ 
        Simple factory to return SMCElement for policy 
        based events such as 'save', 'open', 'export' and 'force_unlock'       
        :param link: entry point based on the link name
        :return: SMCElement
        """
        link_href = self.__load_href(link)    
        return SMCElement.factory(name=link, 
                                  href=link_href)
       
    def __repr__(self):
        return "%s(%r)" % (self.__class__, self.__dict__)

        
class Node(Engine):
    """
    Node is the individual engine level object that handles interfaces, routes and
    operations specific to the individual nodes such as fetching a license, commanding
    a node online, offline or standby, rebooting, getting sginfo, appliance status and
    changing ssh or changing the user password. 
    All inheriting classes will have access to node level commands available in this
    class.
    It is possible to have more than one node in an engine, specifically with clustering.
    """
    def __init__(self, name):
        Engine.__init__(self, name)
        self.name = name        #name of engine
        self.node_type = None   #engine node type
        self.node_links = {}    #node level links
 
    def load(self):
        super(Node, self).load()
        for node in self.engine_json.get('nodes'): #list
            for node_type, node_info in node.iteritems():
                self.node_type = node_type
                #add to dict using node name as {key: [link]}
                self.node_links[node_info.get('name')] = node_info.get('link')
        return self
    
    @classmethod
    def create(cls):
        #nothing to do here, engine has base settings
        return super(Node, cls).create()   
    
    def node_names(self):
        return self.node_links.keys()
        
    def fetch_license(self, node=None):
        """ Allows to fetch the license for the specified node """
        return self._commit_create('fetch', node)

    def bind_license(self, node=None, license_item_id=None):
        """ Allows to bind the optional specified license for the specified 
        node. If no license is specified, an auto bind will be tried.
        
        :param license_item_id: license id, otherwise auto bind will be tried
        """
        params = {'license_item_id': license_item_id}
        return self._commit_create('bind', node, params=params)
        
    def unbind_license(self, node=None):
        """ Allows to unbind the possible already bound license for the 
        specified node. If no license has been found, nothing is done and 
        NO_CONTENT is returned otherwise OK is returned 
        """
        return self._commit_create('unbind', node)
        
    def cancel_unbind_license(self, node):
        """ Allows to cancel the possible unbind license for the specified 
        node. If no license has been found, nothing is done and NO_CONTENT 
        is returned otherwise OK is returned.
        """
        return self._commit_create('cancel_unbind', node)
        
    def initial_contact(self, node=None, enable_ssh=True,
                        time_zone=None, keyboard=None, 
                        install_on_server=None):
        """ Allows to save the initial contact for for the specified node
        
        :param node: node to run initial contact command against
        :param enable_ssh: flag to know if we allow the ssh daemon on the specified node
        :param time_zone: optional time zone to set on the specified node 
        :param keyboard: optional keyboard to set on the specified node
        :param install_on_server: optional flag to know if the generated configuration 
        needs to be installed on SMC Install server (POS is needed)
        """
        print "POST initial contact: %s" % self._load_href('initial_contact')
        element = SMCElement.factory()
        element.href = self._load_href('initial_contact').pop()
        element.params = {'enable_ssh': True}
        print "Element type for initial contact: %s" % type(element)
        print "Element by just print: %s" % element
        print common_api.create(element)
        #print "POST initial contact: %s" % self.__load_href('initial_contact')
        
    def appliance_status(self, node=None):
        """ Gets the appliance status for the specified node 
        for the specific supported engine 
        
        :method: GET
        :param node: Name of node to retrieve from, if single node, can be ignored
        :return: list of status information
        """
        return [search.element_by_href_as_json(status) #TODO: This can return [None]
                for status in self._load_href('appliance_status', node)]

    def status(self, node=None):
        """ Basic status for individual node. Specific information such as node name,
        dynamic package version, configuration status, platform and version.
        
        :method: GET
        :param node: Name of node to retrieve from, otherwise all nodes
        :return: dict of status fields returned from SMC
        """
        return [search.element_by_href_as_json(status) 
                for status in self._load_href('status', node)]
        
    def go_online(self, node=None, comment=None):
        """ Executes a Go-Online operation on the specified node 
        typically done when the node has already been forced offline 
        via :func:`go_offline`
        
        :method: PUT
        :param node: if a cluster, provide the specific node name
        :param comment: optional comment to audit
        :return: href or None
        """
        params = {'comment': comment}
        return self._commit_update('go_online', node, params=params)

    def go_offline(self, node=None, comment=None):
        """ Executes a Go-Offline operation on the specified node
        
        :method: PUT
        :param node: if a cluster, provide the specific node name
        :param comment: optional comment to audit
        :return: href, or None
        """
        params = {'comment': comment}
        return self._commit_update('go_offline', node, params=params)
        
    def go_standby(self, node=None, comment=None):
        """ Executes a Go-Standby operation on the specified node. 
        To get the status of the current node/s, run :func:`status`
        
        :method: PUT
        :param node: if a cluster, provide the specific node name
        :param comment: optional comment to audit
        :return: href, or None
        """
        params = {'comment': comment}
        return self._commit_update('go_standby', node, params=params)
        
    def lock_online(self, node=None, comment=None):
        """ Executes a Lock-Online operation on the specified node
        
        :method: PUT
        :param node: if a cluster, provide the specific node name
        :return: href, or None
        """
        params = {'comment': comment}
        return self._commit_update('lock_online', node, params=params)
        
    def lock_offline(self, node=None, comment=None):
        """ Executes a Lock-Offline operation on the specified node
        Bring back online by running :func:`go_online`.
        
        :method: PUT
        :param node: if a cluster, provide the specific node name
        :return: href or None if failure
        """
        params = {'comment': comment}
        return self._commit_update('lock_offline', node, params=params)
    
    def reset_user_db(self, node=None, comment=None):
        """ 
        Executes a Send Reset LDAP User DB Request operation on the 
        specified node
        
        :method: PUT
        :param node: if a cluster, provide the specific node name
        :param comment: optional comment to audit
        """
        params = {'comment': comment}
        return self._commit_update('reset_user_db', node, params=params)
        
    def diagnostic(self, node=None, filter_enabled=False):
        """ Provide a list of diagnostic options to enable
        #TODO: implement filter_enabled
        :method: GET
        :param node: if a cluster, provide the specific node name
        :param filter_enabled: returns all enabled diagnostics
        :return: list of dict items with diagnostic info
        """
        return [search.element_by_href_as_json(status) 
                for status in self._load_href('diagnostic', node)]
        
    def send_diagnostic(self, node=None):
        """ Send the diagnostics to the specified node 
        Send diagnostics in payload
        """
        print "POST send diagnostic: %s" % self._load_href('send_diagnostic')
        
    def reboot(self, node=None, comment=None):
        """ Reboots the specified node """
        params = {'comment': comment} if comment else None
        return self._commit_update('reboot', node, params=params)
        
    def sginfo(self, node=None, include_core_files=False,
               include_slapcat_output=False):
        """ Get the SG Info of the specified node 
        ?include_core_files
        ?include_slapcat_output
        :param include_core_files: flag to include or not core files
        :param include_slapcat_output: flag to include or not slapcat output
        """
        print "GET sginfo: %s" % self._load_href('sginfo')
        
    def ssh(self, node=None, enable=True, comment=None):
        """ Enable or disable SSH
        
        :method: PUT
        :param enable: enable or disable SSH daemon
        :type enable: boolean
        :param comment: optional comment for audit
        ?enable=
        ?comment=
        """
        params = {'enable': enable, 'comment': comment}
        return self._commit_update('ssh', node, params=params)
        
    def change_ssh_pwd(self, node=None, pwd=None, comment=None):
        """
        Executes a change SSH password operation on the specified node 
        
        :method: PUT
        :param pwd: changed password value
        :param comment: optional comment for audit log
        """
        json = {'value': pwd}
        params = {'comment': comment}
        return self._commit_update('change_ssh_pwd', node, json=json, 
                                   params=params)
        
    def time_sync(self, node=None):
        return self._commit_update('time_sync', node)
      
    def certificate_info(self, node=None):
        """ Get the certificate info of the specified node 
        
        :return: list with links to cert info
        """
        return [search.element_by_href_as_json(status) 
                for status in self._load_href('certificate_info', node)]
       
    def _commit_create(self, action, node, params=None):
        href = self._load_href(action, node)
        if href:
            element = SMCElement.factory(href=href.pop(),
                                         params=params)
            return common_api.create(element)
                                                    
    def _commit_update(self, action, node, json=None, params=None):
        href = self._load_href(action, node)
        if href:
            element = SMCElement.factory(href=href.pop(),
                                         json=json,
                                         params=params,
                                         etag=self.etag)
            return common_api.update(element)
                   
    def _load_href(self, action, node=None):
        """ Get href from self.node_links cache based on the node name. 
        If this is a cluster, the node parameter is required. 
        Since these are node level commands, we need to be able to specify
        which node to run against. If not a cluster, then node param is not
        required and is ignored if given.
        :param action: link to get
        :param node: name of node, only used for clusters with multiple nodes
        :return: list of href, or []
        """
        if not self.cluster_mode: #ignore node if single device node
            href = [link.get('href')
                    for node, links in self.node_links.iteritems()
                    for link in links
                    if link.get('rel') == action]
        else: #require node for cluster
            if node and node in self.node_links.keys():
                href = [entry.get('href') 
                        for entry in self.node_links.get(node)
                        if entry.get('rel') == action]
            else:
                return []
        return href

        
class Layer3Firewall(Node):
    """
    Represents a Layer 3 Firewall configuration.
    To instantiate and create, call 'create' classmethod as follows::
    
        engine = Layer3Firewall.create('mylayer3', '1.1.1.1', '1.1.1.0/24', href_to_log_server)
        
    """ 
    def __init__(self, name):
        Node.__init__(self, name)
        self.node_type = 'firewall_node'

    @classmethod   
    def create(cls, name, mgmt_ip, mgmt_network, log_server=None,
                 mgmt_interface='0', dns=None):
        """ 
        Create a single layer 3 firewall with management interface and DNS
        
        :param name: name of firewall
        :param name: management network ip
        :param mgmt_network: management network in cidr format
        :param log_server: href to log_server instance for fw
        :param mgmt_interface: interface for management from SMC to fw
        :type mgmt_interface: string or None
        :param dns: DNS server addresses
        :type dns: list or None
        :return: Layer3Firewall class with href and engine_json set
        """
        cls.name = name
        cls.node_type = 'firewall_node'
        cls.log_server_ref = log_server if log_server \
            else SystemInfo().first_log_server()  
        cls.domain_server_address = []
        if dns:
            for entry in dns:
                cls.domain_server_address.append(entry)
        
        super(Layer3Firewall, cls).create()
        mgmt = l3_mgmt_interface(mgmt_ip, mgmt_network, 
                                 interface_id=mgmt_interface)
        cls.engine_json.get('physicalInterfaces').append(mgmt.json)
        cls.href = search.element_entry_point('single_fw')
        return cls #json    
    

class Layer2Firewall(Node):
    """
    Represents a Layer2 Firewall configuration.
    To instantiate and create, call 'create' classmethod as follows::
    
        engine = Layer2Firewall.create('mylayer2', '1.1.1.1', '1.1.1.0/24', href_to_log_server)
        
    """ 
    def __init__(self, name):
        Node.__init__(self, name)
        self.node_type = 'fwlayer2_node'
    
    @classmethod
    def create(cls, name, mgmt_ip, mgmt_network, 
               log_server=None, mgmt_interface='0', 
               inline_interface='1-2', logical_interface='default_eth', 
               dns=None):
        """ 
        Create a single layer 2 firewall with management interface, inline interface,
        and DNS
        
        :param name: name of firewall
        :param name: management network ip
        :param mgmt_network: management network in cidr format
        :param log_server: href to log_server instance for fw
        :param mgmt_interface: interface for management from SMC to fw
        :type mgmt_interface: string or None
        :param inline_interface: interface ID's to use for default inline interfaces
        :type inline_interface: string or None (i.e. '1-2')
        :param logical_interface: logical interface to assign to inline interface
        :type logical_interface: string or None
        :param dns: DNS server addresses
        :type dns: list or None
        :return: Layer2Firewall class with href and engine_json set
        """
        cls.name = name
        cls.node_type = 'fwlayer2_node'
        cls.log_server_ref = log_server if log_server \
            else SystemInfo().first_log_server()
        cls.domain_server_address = []
        if dns:
            for entry in dns:
                cls.domain_server_address.append(entry)
        
        super(Layer2Firewall, cls).create()
        mgmt = l2_mgmt_interface(mgmt_ip, mgmt_network, 
                                 interface_id=mgmt_interface)
        
        intf_href = search.get_logical_interface(logical_interface)
        inline = inline_intf(intf_href, interface_id=inline_interface)
    
        cls.engine_json.get('physicalInterfaces').append(mgmt.json)
        cls.engine_json.get('physicalInterfaces').append(inline.json)
        cls.href = search.element_entry_point('single_layer2')
        return cls
        

class IPS(Node):
    """
    Represents an IPS engine configuration.
    To instantiate and create, call 'create' classmethod as follows::
    
        engine = IPS.create('myips', '1.1.1.1', '1.1.1.0/24')
        
    """ 
    def __init__(self, name):
        Node.__init__(self, name)
        self.node_type = 'ips_node'

    @classmethod
    def create(cls, name, mgmt_ip, mgmt_network, 
               log_server=None, mgmt_interface='0', 
               inline_interface='1-2', logical_interface='default_eth', 
               dns=None):
        """ 
        Create a single layer 2 firewall with management interface, inline interface
        and DNS
        
        :param name: name of ips engine
        :param name: management network ip
        :param mgmt_network: management network in cidr format
        :param log_server: href to log_server instance for fw
        :param mgmt_interface: interface for management from SMC to fw
        :type mgmt_interface: string or None
        :param inline_interface: interface ID's to use for default inline interfaces
        :type inline_interface: string or None (i.e. '1-2')
        :param logical_interface: logical interface to assign to inline interface
        :type logical_interface: string or None
        :param dns: DNS server addresses
        :type dns: list or None
        :return: IPS class with href and engine_json set
        """
        cls.name = name
        cls.node_type = 'ips_node'
        cls.log_server_ref = log_server if log_server \
            else SystemInfo().first_log_server()
        cls.domain_server_address = []
        if dns:
            for entry in dns:
                cls.domain_server_address.append(entry)
                       
        super(IPS, cls).create()
        mgmt = l2_mgmt_interface(mgmt_ip, mgmt_network, 
                                interface_id=mgmt_interface)
            
        intf_href = search.get_logical_interface(logical_interface)
        inline = inline_intf(intf_href, interface_id=inline_interface)
        
        cls.engine_json.get('physicalInterfaces').append(mgmt.json)
        cls.engine_json.get('physicalInterfaces').append(inline.json)
        cls.href = search.element_entry_point('single_ips')
        return cls

def async_handler(element, wait_for_finish=True, 
                  sleep_interval=3, 
                  display_msg=True):
    """ Handles asynchronous operations called on engine or node levels
    
    :param element: The element to be sent to SMC
    :param wait_for_finish: whether to wait for it to finish or not
    :param display_msg: whether to return display messages or not
    :param sleep_interval: how long to wait between async checks
    
    If wait_for_finish is False, the generator will yield the follower 
    href only. If true, will return messages as they arrive and location 
    to the result after complete.
    To obtain messages as they arrive, call the async method in a for loop::
        for msg in engine.export():
            print msg
    """
    import time
    upload = common_api.create(element)
    if upload.json:
        if wait_for_finish:
            last_msg = ''
            while True:
                status = search.element_by_href_as_json(upload.json.get('follower'))
                msg = status.get('last_message')
                if display_msg:
                    if msg != last_msg:
                        #yield re.sub(cleanr,'', msg)
                        yield msg
                        last_msg = msg
                if status.get('success') == True:
                    for link in status.get('link'):
                        if link.get('rel') == 'result':
                            yield link.get('href')
                    break
                time.sleep(sleep_interval)
        else:
            yield upload.json.get('follower')

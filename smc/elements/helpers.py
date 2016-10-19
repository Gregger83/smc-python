"""
Helper functions to retrieve various elements that may be required by specific
constructors.
"""
import smc.actions.search as search
from element import Zone, LogicalInterface, Location
      
def location_helper(name):
    """
    Location finder by name. If location doesn't exist, create it
    and return the href
    
    :param str name
    :return str href: href of location
    """
    location = [x
                for x in search.all_elements_by_type('location')
                if x.get('name') == name]
    if location:
        return location[0].get('href')    
    else:
        return Location.create(name).href

def zone_helper(zone):
    """
    Zone finder by name. If zone doesn't exist, create it and
    return the href

    :param str zone: name of zone
    :return str href: href of zone
    """
    zone_ref = search.element_href_use_filter(zone, 'interface_zone')
    if zone_ref:
        return zone_ref
    else:
        return Zone.create(zone).href
    
def logical_intf_helper(interface):
    """
    Logical Interface finder by name. Create if it doesn't exist
    
    :param interface: logical interface name
    :return str href: href of logical interface
    """
    intf_ref = search.element_href_use_filter(interface, 'logical_interface')
    if intf_ref:
        return intf_ref
    else:
        return LogicalInterface.create(interface).href

def domain_helper(name):
    """
    Find a domain based on name
    
    :return: str href: href of domain
    """
    domain = search.element_href_use_filter(name, 'admin_domain')
    if domain:
        return domain

def fw_templates(name):
    """
    Find the FW template href by name
    
    :return: str href of template or None
    """
    return search.element_href_use_filter(name, 'fw_template_policy')

def obtain_element(name, typeof):
    print "CALLED OBTAIN ELEMENT"
    element = search.element_info_as_json_with_filter(name, typeof)
    if element:    
        print "Element: %s" % element
    return element
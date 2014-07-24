# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
# Copyright 2013 Mellanox Technologies, Ltd
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import re
from nova import exception
from nova.openstack.common import log as logging
from nova.openstack.common import processutils
from nova import utils
from nova.openstack.common.gettextutils import _
from nova.virt.libvirt import vif
from mlnxvif import config  as mlxconfig

LOG = logging.getLogger(__name__)
HEX_BASE = 16
VIF_TYPE_HOSTDEV = 'hostdev'


class MlxEthVIFDriver(vif.LibvirtBaseVIFDriver):
    """VIF driver for Mellanox Embedded switch Plugin"""
    def __init__(self, get_connection):
        super(MlxEthVIFDriver, self).__init__(get_connection)
        self.libvirt_gen_drv = vif.LibvirtGenericVIFDriver(get_connection)

    def get_dev_config(self, mac_address, dev):
        conf = None
        conf = mlxconfig.MlxLibvirtConfigGuestDevice()
        self._set_source_address(conf, dev)
        return conf

    def get_config(self, instance, vif, image_meta,
                   inst_type):
        vif_type = vif.get('type')
        if vif_type != VIF_TYPE_HOSTDEV:
            conf = self.libvirt_gen_drv.get_config(instance, vif,
                                                   image_meta, inst_type)
        else:
            LOG.debug(_("vif_type=%s"), vif_type)
            dev_name = None
            dev = None
            device_id = instance['uuid']
            vnic_mac = vif['address']
            network = vif['network']
            fabric = vif.get_physical_network()
            if not fabric:
                raise exception.NetworkMissingPhysicalNetwork(
                    network_uuid=vif['network']['id'])

            try:
                res = utils.execute('ebrctl', 'allocate-port',
                                    vnic_mac, device_id, fabric,
                                    vif_type, run_as_root=True)
                dev = res[0].strip()

            except processutils.ProcessExecutionError:
                LOG.exception(_("Failed while config vif"),
                              instance=instance)
                raise exception.NovaException(_("Processing Failure during "
                                                "vNIC allocation"))
            #Allocation Failed
            if dev is None:
                raise exception.NovaException(_("Failed to allocate "
                                            "device for vNIC"))
            conf = self.get_dev_config(vnic_mac, dev)
        return conf

    def plug(self, instance, vif):
        vif_type = vif.get('type')
        if vif_type != VIF_TYPE_HOSTDEV:
            self.libvirt_gen_drv.plug(instance, vif)
        else:
                LOG.debug(_("vif_type=%s"), vif_type)
                network = vif['network']
                vnic_mac = vif['address']
                device_id = instance['uuid']
                dev_name = None
                dev = None
                fabric = vif.get_physical_network()
                if not fabric:
                    raise exception.NetworkMissingPhysicalNetwork(
                        network_uuid=vif['network']['id'])

                try:
                    dev = utils.execute('ebrctl', 'add-port', vnic_mac,
                                        device_id, fabric, vif_type, dev_name,
                                        run_as_root=True)
                    if dev:
                        return
                    else:
                        error_msg = "Cannot plug VIF with no allocated device"
                        LOG.warning(_(error_msg))
                except Exception:
                    LOG.exception(_("Processing Failure during vNIC plug"))

    def unplug(self, instance, vif):
        vif_type = vif.get('type')
        if vif_type != VIF_TYPE_HOSTDEV:
            self.libvirt_gen_drv.unplug(instance, vif)
        else:
                LOG.debug(_("vif_type=%s"), vif_type)
                network = vif['network']
                vnic_mac = vif['address']
                fabric = vif.get_physical_network()

                if not fabric:
                   raise exception.NetworkMissingPhysicalNetwork(
                        network_uuid=vif['network']['id'])

                try:
                    utils.execute('ebrctl', 'del-port', fabric,
                              vnic_mac, run_as_root=True)
                except Exception:
                    LOG.exception(_("Failed while unplugging vif"))

    def _str_to_hex(self, str_val):
        ret_val = hex(int(str_val, HEX_BASE))
        return ret_val

    def _set_source_address(self, conf, dev):
        source_address = re.split(r"\.|\:", dev)
        conf.domain, conf.bus, conf.slot, conf.function = source_address
        conf.domain = self._str_to_hex(conf.domain)
        conf.bus = self._str_to_hex(conf.bus)
        conf.slot = self._str_to_hex(conf.slot)
        conf.function = self._str_to_hex(conf.function)

# Copyright 2014 Mellanox Technologies, Ltd
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
import contextlib
from lxml import etree
import mock
from oslo.config import cfg
import testtools

from nova.compute import flavors
from nova import exception
from nova.network import linux_net
from nova.network import model as network_model
from nova.openstack.common import processutils
from nova import test
from nova.tests.virt.libvirt import fakelibvirt
from nova import utils
from nova.virt.libvirt import config as vconfig
from nova.virt.libvirt import vif
from mlnxvif import vif as mlnx_vif

CONF = cfg.CONF


class LibvirtVifTestCase(test.TestCase):

    gateway_bridge_4 = network_model.IP(address='101.168.1.1', type='gateway')
    dns_bridge_4 = network_model.IP(address='8.8.8.8', type=None)
    subnet_bridge_4 = network_model.Subnet(cidr='101.168.1.0/24',
                                           dns=[dns_bridge_4],
                                           gateway=gateway_bridge_4,
                                           routes=None,
                                           dhcp_server='191.168.1.1')

    gateway_bridge_6 = network_model.IP(address='101:1db9::1', type='gateway')
    subnet_bridge_6 = network_model.Subnet(cidr='101:1db9::/64',
                                           dns=None,
                                           gateway=gateway_bridge_6,
                                           ips=None,
                                           routes=None)

    network_ovs = network_model.Network(id='network-id-xxx-yyy-zzz',
                                        bridge='br0',
                                        label=None,
                                        subnets=[subnet_bridge_4,
                                                 subnet_bridge_6],
                                        bridge_interface=None,
                                        vlan=99)

    network_mlnx = network_model.Network(id='network-id-xxx-yyy-zzz',
                                         label=None,
                                         bridge=None,
                                         subnets=[subnet_bridge_4,
                                                  subnet_bridge_6],
                                         meta={'physical_network': 'default'},
                                         interface='eth0')

    network_mlnx_none = network_model.Network(id='network-id-xxx-yyy-zzz',
                                              label=None,
                                              bridge=None,
                                              subnets=[subnet_bridge_4,
                                              subnet_bridge_6],
                                              meta={'physical_network': None},
                                              interface='eth0')

    vif_mlnx_hostdev = network_model.VIF(id='vif-xxx-yyy-zzz',
                                         address='ca:fe:de:ad:be:ef',
                                         network=network_mlnx,
                                         type=mlnx_vif.VIF_TYPE_HOSTDEV,
                                         devname='tap-xxx-yyy-zzz')

    vif_mlnx_hostdev_none = network_model.VIF(id='vif-xxx-yyy-zzz',
                                              address='ca:fe:de:ad:be:ef',
                                              network=network_mlnx_none,
                                              type='hostdev',
                                              devname='tap-xxx-yyy-zzz')

    vif_ovs = network_model.VIF(id='vif-xxx-yyy-zzz',
                                address='ca:fe:de:ad:be:ef',
                                network=network_ovs,
                                type=network_model.VIF_TYPE_OVS,
                                devname='tap-xxx-yyy-zzz',
                                ovs_interfaceid='aaa-bbb-ccc')

    instance = {
        'name': 'instance-name',
        'uuid': 'instance-uuid',
        'project_id': 'myproject'
    }

    def setUp(self):
        super(LibvirtVifTestCase, self).setUp()
        self.flags(allow_same_net_traffic=True)
        self.executes = []

        def fake_execute(*cmd, **kwargs):
            self.executes.append(cmd)
            return None, None

        self.stubs.Set(utils, 'execute', fake_execute)

    def _get_conn(self, uri="qemu:///session", ver=None):
        def __inner():
            if ver is None:
                return fakelibvirt.Connection(uri, False)
            else:
                return fakelibvirt.Connection(uri, False, ver)
        return __inner

    def test_plug_mlnx_hostdev(self):
        vif_gen = vif.LibvirtGenericVIFDriver
        d = mlnx_vif.MlxEthVIFDriver(self._get_conn(ver=9010))
        with mock.patch.object(utils, 'execute') as execute:
            with mock.patch.object(vif_gen, 'plug') as gen_plug:
                d.plug(self.instance, self.vif_mlnx_hostdev)
                self.assertEqual(gen_plug.call_count, 0)

    def test_unplug_mlnx_hostdev(self):
        vif_gen = vif.LibvirtGenericVIFDriver
        d = mlnx_vif.MlxEthVIFDriver(self._get_conn(ver=9010))
        with mock.patch.object(utils, 'execute') as execute:
            with mock.patch.object(vif_gen, 'unplug') as gen_unplug:
                d.unplug(self.instance, self.vif_mlnx_hostdev)
                self.assertEqual(gen_unplug.call_count, 0)

    def test_plug_mlnx_hostdev_fabric_none(self):
        d = mlnx_vif.MlxEthVIFDriver(self._get_conn(ver=9010))
        with mock.patch('mlnxvif.vif.LOG') as log_mock:
            d.plug(self.instance, self.vif_mlnx_hostdev_none)
            log_mock.warning.assert_called_with("Cannot plug VIF. "
                                                "Fabric is expected")

    def test_plug_mlnx_hostdev_ovs_vif(self):
        d = mlnx_vif.MlxEthVIFDriver(self._get_conn(ver=9010))
        with mock.patch.object(vif.LibvirtGenericVIFDriver, 'plug') as plug:
            d.plug(self.instance, self.vif_ovs)
        self.assertEqual(plug.call_count, 1)

    def test_plug_mlnx_hostdev_not_allocated(self):
        d = mlnx_vif.MlxEthVIFDriver(self._get_conn(ver=9010))
        with mock.patch.object(utils, 'execute', return_value=None) as execute:
            with mock.patch('mlnxvif.vif.LOG') as log_mock:
                d.plug(self.instance, self.vif_mlnx_hostdev)
                log_mock.warning.assert_called_with("Cannot plug VIF with "
                                                    "no allocated device")

    def test_unplug_mlnx_hostdev_none(self):
        d = mlnx_vif.MlxEthVIFDriver(self._get_conn(ver=9010))
        with mock.patch('mlnxvif.vif.LOG') as log_mock:
            d.unplug(self.instance, self.vif_mlnx_hostdev_none)
            log_mock.warning.assert_called_with("Cannot unplug VIF. "
                                                "Fabric is expected")

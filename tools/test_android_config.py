"""Regression checks for the network-security configuration used by Android Lint."""
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'mobile/android/app/src/main/res/xml/network_security_config.xml'


class AndroidNetworkSecurityTests(unittest.TestCase):
    def setUp(self):
        self.root = ET.parse(CONFIG).getroot()

    def test_domains_explicitly_exclude_subdomains(self):
        for domain in self.root.findall('.//domain'):
            with self.subTest(domain=domain.text):
                self.assertEqual('false', domain.get('includeSubdomains'))

    def test_cleartext_is_limited_to_local_development_hosts(self):
        self.assertEqual('false', self.root.find('base-config').get('cleartextTrafficPermitted'))
        hosts = set()
        for config in self.root.findall('.//domain-config'):
            if config.get('cleartextTrafficPermitted') == 'true':
                domains = config.findall('domain')
                self.assertTrue(domains)
                hosts.update(domain.text for domain in domains)
        self.assertEqual({'localhost', '127.0.0.1', '10.0.2.2'}, hosts)

    def test_user_installed_certificates_are_not_globally_trusted(self):
        self.assertFalse(self.root.findall('.//certificates[@src="user"]'))


if __name__ == '__main__':
    unittest.main()

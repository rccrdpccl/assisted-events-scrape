import unittest

from repositories.cluster_repository import ClusterRepository
from assisted_service_client import rest
from unittest.mock import Mock


class TestClusterRepository(unittest.TestCase):
    def setUp(self):
        self.mock_hosts = [
            {"id": "123", "hostname": "foo"},
            {"id": "123", "hostname": "bar"},
        ]
        self.mock_clusters_list = [
            {"id": "abc"},
            {"id": "def"}
        ]
        self.client_mock = Mock()

    def test_list_clusters(self):
        self.client_mock.clusters_list.side_effect = [self.mock_clusters_list]

        cr = ClusterRepository(self.client_mock)
        clusters = cr.list_clusters()

        self.client_mock.clusters_list.assert_called_once()
        self.assertListEqual(clusters, self.mock_clusters_list)

    def test_get_cluster_hosts(self):
        self.client_mock.get_cluster_hosts.side_effect = [self.mock_hosts]

        cr = ClusterRepository(self.client_mock)
        hosts = cr.get_cluster_hosts("my_cluster_id")

        self.client_mock.get_cluster_hosts.assert_called_once()
        self.assertListEqual(hosts, self.mock_hosts)

    def test_get_cluster_hosts_exception(self):
        exception = Exception("Just a generic exception")
        self.client_mock.get_cluster_hosts.side_effect = exception

        cr = ClusterRepository(self.client_mock)

        with self.assertRaises(Exception):
            cr.get_cluster_hosts("my_cluster_id")

    def test_get_cluster_hosts_not_found(self):
        exception = rest.ApiException("Not found")
        exception.reason = "Not Found"
        self.client_mock.get_cluster_hosts.side_effect = exception

        cr = ClusterRepository(self.client_mock)

        hosts = cr.get_cluster_hosts("my_cluster_id")
        self.assertEquals([], hosts)

    def test_get_cluster_hosts_api_exception(self):
        exception = rest.ApiException("NOT Not found")
        exception.reason = "NOT Not Found"
        self.client_mock.get_cluster_hosts.side_effect = exception

        cr = ClusterRepository(self.client_mock)

        with self.assertRaises(rest.ApiException):
            cr.get_cluster_hosts("my_cluster_id")

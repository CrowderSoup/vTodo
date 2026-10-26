package com.crowdersoup.vtodo

import com.crowdersoup.vtodo.data.isLocalNetworkHost
import com.crowdersoup.vtodo.data.normalizeBaseUrl
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class ServerUrlTest {
    @Test
    fun addsHttpsAndStripsApiSuffix() {
        assertEquals("https://vtodo.example.com", normalizeBaseUrl("vtodo.example.com"))
        assertEquals("https://vtodo.example.com", normalizeBaseUrl("https://vtodo.example.com/"))
        assertEquals("https://vtodo.example.com", normalizeBaseUrl("https://vtodo.example.com/api/v1"))
    }

    @Test
    fun keepsExplicitHttpHostAndPort() {
        assertEquals("http://192.168.0.20:8000", normalizeBaseUrl("http://192.168.0.20:8000/"))
    }

    @Test
    fun rejectsBlankAndHostlessUrls() {
        assertThrows(IllegalArgumentException::class.java) { normalizeBaseUrl("  ") }
        assertThrows(IllegalArgumentException::class.java) { normalizeBaseUrl("https://") }
    }

    @Test
    fun rejectsHttpForAnInternetServer() {
        assertThrows(IllegalArgumentException::class.java) { normalizeBaseUrl("http://vtodo.example.com") }
        assertThrows(IllegalArgumentException::class.java) { normalizeBaseUrl("http://8.8.8.8:8000") }
        assertEquals("https://vtodo.example.com", normalizeBaseUrl("https://vtodo.example.com"))
    }

    @Test
    fun allowsHttpOnTheLocalNetwork() {
        listOf(
            "localhost", "127.0.0.1", "10.0.2.2", "172.16.4.1", "172.31.255.255", "192.168.1.5",
            "169.254.1.1", "100.101.102.103", "nas", "nas.local", "pi.lan", "box.home.arpa",
            "app.internal", "[::1]", "0:0:0:0:0:0:0:1", "[fd12:3456::1]", "[fe80::1]",
            "[::ffff:192.168.1.1]",
        ).forEach { host -> assertTrue(host, isLocalNetworkHost(host)) }
    }

    @Test
    fun treatsPublicAddressesAsInternet() {
        listOf(
            "vtodo.example.com", "8.8.8.8", "172.32.0.1", "192.169.0.1", "100.128.0.1",
            "[2001:db8::1]", "fc::1", "fd::1", "fe8::1", "fe9::1", "[::ffff:8.8.8.8]", "local.example.com",
        ).forEach { host -> assertFalse(host, isLocalNetworkHost(host)) }
    }
}

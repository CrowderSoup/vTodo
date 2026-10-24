package com.crowdersoup.vtodo

import com.crowdersoup.vtodo.data.normalizeBaseUrl
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
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
}

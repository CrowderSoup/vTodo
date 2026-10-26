package com.crowdersoup.vtodo

import com.crowdersoup.vtodo.data.VtodoApiException
import com.crowdersoup.vtodo.data.nextPageUrl
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Test

class NextPageUrlTest {
    private val base = "https://vtodo.example.com"

    @Test
    fun lastPageHasNoNext() {
        assertNull(nextPageUrl(base, null))
        assertNull(nextPageUrl(base, JsonNull))
        assertNull(nextPageUrl(base, JsonPrimitive("")))
    }

    @Test
    fun followsNextOnTheSameServer() {
        val next = "https://vtodo.example.com/api/v1/tasks/?open=true&page=2"
        assertEquals(next, nextPageUrl(base, JsonPrimitive(next)))
    }

    @Test
    fun refusesToSendTheTokenElsewhere() {
        listOf(
            "https://evil.example.com/api/v1/tasks/?page=2",
            "https://vtodo.example.com.evil.example/api/v1/tasks/?page=2",
            "http://vtodo.example.com/api/v1/tasks/?page=2",
        ).forEach { next ->
            assertThrows(next, VtodoApiException::class.java) { nextPageUrl(base, JsonPrimitive(next)) }
        }
    }
}

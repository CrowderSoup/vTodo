package com.crowdersoup.vtodo.data

import java.net.URI
import java.net.URISyntaxException

fun normalizeBaseUrl(raw: String): String {
    var value = raw.trim()
    if (value.isEmpty()) throw IllegalArgumentException("Server URL is required.")
    if (!value.startsWith("http://") && !value.startsWith("https://")) {
        value = "https://$value"
    }
    value = value.trimEnd('/')
    if (value.endsWith("/api/v1")) {
        value = value.removeSuffix("/api/v1")
    }
    val uri = try {
        URI(value)
    } catch (_: URISyntaxException) {
        throw IllegalArgumentException("Server URL is not valid.")
    }
    if (uri.host.isNullOrBlank()) throw IllegalArgumentException("Server URL is not valid.")
    return value
}

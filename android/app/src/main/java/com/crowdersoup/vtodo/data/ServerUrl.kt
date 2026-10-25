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
    val host = uri.host
    if (host.isNullOrBlank()) throw IllegalArgumentException("Server URL is not valid.")
    // The API token is a permanent credential and goes in every request, so
    // plain http is only allowed where it never leaves the local network.
    if (uri.scheme == "http" && !isLocalNetworkHost(host)) {
        throw IllegalArgumentException(
            "Use https:// for a server on the internet. http:// only works for a server on your home network.",
        )
    }
    return value
}

private val localSuffixes = listOf(".local", ".lan", ".home.arpa", ".internal")

/** Loopback, private and link-local addresses, and LAN-only names. No DNS lookup. */
internal fun isLocalNetworkHost(rawHost: String): Boolean {
    val host = rawHost.lowercase().removePrefix("[").removeSuffix("]").trimEnd('.')
    if (host == "localhost" || localSuffixes.any { host.endsWith(it) }) return true
    ipv4(host)?.let { (a, b) ->
        return a == 10 ||
            a == 127 ||
            (a == 172 && b in 16..31) ||
            (a == 192 && b == 168) ||
            (a == 169 && b == 254) ||
            (a == 100 && b in 64..127) // carrier-grade NAT, which Tailscale uses
    }
    if (':' in host) {
        return host == "::1" ||
            host.startsWith("fc") ||
            host.startsWith("fd") ||
            host.startsWith("fe8") ||
            host.startsWith("fe9") ||
            host.startsWith("fea") ||
            host.startsWith("feb")
    }
    // A name with no dot only resolves through the local network's DNS.
    return '.' !in host
}

private fun ipv4(host: String): Pair<Int, Int>? {
    val parts = host.split('.')
    if (parts.size != 4) return null
    val octets = parts.map { part -> part.toIntOrNull()?.takeIf { it in 0..255 } ?: return null }
    return octets[0] to octets[1]
}

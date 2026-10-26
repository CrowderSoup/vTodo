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
    ipv4(host)?.let { return isLocalV4(it) }
    // Match the address, not its spelling. Compression drops leading zeros,
    // so "fc::1" is not inside fc00::/7.
    if (':' in host) return isLocalV6(host.substringBefore('%'))
    // A name with no dot only resolves through the local network's DNS.
    return '.' !in host
}

private fun isLocalV4(octets: Pair<Int, Int>): Boolean {
    val (a, b) = octets
    return a == 10 ||
        a == 127 ||
        (a == 172 && b in 16..31) ||
        (a == 192 && b == 168) ||
        (a == 169 && b == 254) ||
        (a == 100 && b in 64..127) // carrier-grade NAT, which Tailscale uses
}

private fun ipv4(host: String): Pair<Int, Int>? {
    val parts = host.split('.')
    if (parts.size != 4) return null
    val octets = parts.map { part -> part.toIntOrNull()?.takeIf { it in 0..255 } ?: return null }
    return octets[0] to octets[1]
}

private fun isLocalV6(host: String): Boolean {
    val hextets = expandV6(host) ?: return false
    if (hextets[0] == 0 && hextets[1] == 0 && hextets[2] == 0 &&
        hextets[3] == 0 && hextets[4] == 0 && hextets[5] == 0xffff
    ) {
        return isLocalV4((hextets[6] ushr 8) to (hextets[6] and 0xff))
    }
    if (hextets.take(7).all { it == 0 } && hextets[7] == 1) return true
    val first = hextets[0]
    return first in 0xfc00..0xfdff || first in 0xfe80..0xfebf
}

private fun expandV6(host: String): IntArray? {
    if (":::" in host || host.count { it == ':' } < 2) return null
    if (host.indexOf("::") != host.lastIndexOf("::")) return null
    var body = host
    val mapped = ArrayList<Int>(2)
    val tailColon = body.lastIndexOf(':')
    val tail = if (tailColon >= 0) body.substring(tailColon + 1) else ""
    if ('.' in tail) {
        if (ipv4(tail) == null) return null
        val octets = tail.split('.').map { it.toInt() }
        mapped += (octets[0] shl 8) or octets[1]
        mapped += (octets[2] shl 8) or octets[3]
        body = body.substring(0, tailColon)
    }
    val groups = if ("::" in body) {
        val sides = body.split("::")
        val left = if (sides[0].isEmpty()) emptyList() else sides[0].split(':')
        val right = if (sides[1].isEmpty()) emptyList() else sides[1].split(':')
        val missing = 8 - mapped.size - left.size - right.size
        if (missing < 1) return null
        left + List(missing) { "0" } + right
    } else {
        body.split(':')
    }
    if (groups.size + mapped.size != 8) return null
    val values = groups.map { group ->
        if (group.isEmpty() || group.length > 4) return null
        group.toIntOrNull(16)?.takeIf { it in 0..0xffff } ?: return null
    }
    return (values + mapped).toIntArray()
}

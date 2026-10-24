package com.crowdersoup.vtodo

import com.crowdersoup.vtodo.brand.Brand
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Test
import java.io.File

class BrandTest {
    @Test
    fun colorsMatchTheWebsiteCss() {
        val css = repoFile("static/app.css").readText()
        val light = colors(css, ":root")
        val dark = colors(css, "[data-theme=\"dark\"]")
        assertEquals(light.getValue("--bg"), Brand.BG)
        assertEquals(light.getValue("--bg-elevated"), Brand.BG_ELEVATED)
        assertEquals(light.getValue("--text"), Brand.TEXT)
        assertEquals(light.getValue("--text-soft"), Brand.TEXT_SOFT)
        assertEquals(light.getValue("--accent"), Brand.ACCENT)
        assertEquals(light.getValue("--danger"), Brand.DANGER)
        assertEquals(dark.getValue("--bg"), Brand.DARK_BG)
        assertEquals(dark.getValue("--bg-elevated"), Brand.DARK_BG_ELEVATED)
        assertEquals(dark.getValue("--text"), Brand.DARK_TEXT)
        assertEquals(dark.getValue("--text-soft"), Brand.DARK_TEXT_SOFT)
        assertEquals(dark.getValue("--accent"), Brand.DARK_ACCENT)
        assertEquals(dark.getValue("--danger"), Brand.DARK_DANGER)
    }

    @Test
    fun launcherIconIsTheWebsiteLogo() {
        val logo = repoFile("static/logo.png").readBytes()
        val generated = moduleFile("build/generated/brand/res/drawable-nodpi/ic_brand_logo.png").readBytes()
        assertArrayEquals(logo, generated)
    }

    private fun colors(css: String, marker: String): Map<String, Long> {
        val start = css.indexOf(marker)
        val open = css.indexOf('{', start)
        val close = css.indexOf('}', open)
        val body = css.substring(open + 1, close)
        return Regex("""(--[a-z0-9-]+)\s*:\s*#([0-9A-Fa-f]{6})""")
            .findAll(body)
            .associate { it.groupValues[1] to (it.groupValues[2].toLong(16) or 0xFF000000L) }
    }

    private fun repoFile(relative: String): File {
        val candidates = listOf(File(relative), File("../../$relative"))
        return candidates.firstOrNull { it.isFile } ?: error("Missing $relative from ${File(".").absolutePath}")
    }

    private fun moduleFile(relative: String): File {
        val candidates = listOf(File(relative), File("android/app/$relative"))
        return candidates.firstOrNull { it.isFile } ?: error("Missing $relative from ${File(".").absolutePath}")
    }
}

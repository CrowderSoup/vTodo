package com.crowdersoup.vtodo.today

sealed interface NoteBlock {
    data class Heading(val level: Int, val inlines: List<NoteInline>) : NoteBlock
    data class Paragraph(val inlines: List<NoteInline>) : NoteBlock
    data class Bullets(val items: List<NoteListItem>) : NoteBlock
    data class Numbered(val items: List<NoteListItem>) : NoteBlock
    data class Quote(val blocks: List<NoteBlock>) : NoteBlock
    data class Code(val text: String) : NoteBlock
    data object Rule : NoteBlock
    data class Table(val header: List<List<NoteInline>>, val rows: List<List<List<NoteInline>>>) : NoteBlock
}

data class NoteListItem(val checked: Boolean?, val inlines: List<NoteInline>)

sealed interface NoteInline {
    data class Text(val text: String) : NoteInline
    data class Strong(val children: List<NoteInline>) : NoteInline
    data class Emphasis(val children: List<NoteInline>) : NoteInline
    data class Strike(val children: List<NoteInline>) : NoteInline
    data class Code(val text: String) : NoteInline
    data class Link(val children: List<NoteInline>, val url: String) : NoteInline
}

private val fenceRegex = Regex("""^ {0,3}(`{3,}|~{3,})(.*)$""")
private val headingRegex = Regex("""^ {0,3}(#{1,6})\s+(\S.*?)\s*#*\s*$""")
private val listRegex = Regex("""^(\s*)([-*+]|\d+[.)])\s+(.*)$""")
private val ruleRegex = Regex("""^\s*([-*_])(?:\s*\1){2,}\s*$""")
private val checkboxRegex = Regex("""^\[([xX ])]\s*(.*)$""")
private val separatorCell = Regex(""":?-{3,}:?""")

fun parseNotes(markdown: String): List<NoteBlock> {
    val lines = markdown.replace("\r\n", "\n").replace('\r', '\n').lines()
    return parseBlocks(lines)
}

private fun parseBlocks(lines: List<String>): List<NoteBlock> {
    val blocks = mutableListOf<NoteBlock>()
    var i = 0
    while (i < lines.size) {
        if (lines[i].isBlank()) {
            i++
            continue
        }
        val fence = fenceOf(lines[i])
        if (fence != null) {
            val body = mutableListOf<String>()
            i++
            while (i < lines.size && !closesFence(lines[i], fence)) {
                body += lines[i]
                i++
            }
            if (i < lines.size) i++
            blocks += NoteBlock.Code(body.joinToString("\n"))
            continue
        }
        if (isTableStart(lines, i)) {
            val parsed = parseTable(lines, i)
            blocks += parsed.first
            i = parsed.second
            continue
        }
        if (isListLine(lines[i])) {
            val parsed = parseList(lines, i)
            blocks += parsed.first
            i = parsed.second
            continue
        }
        if (lines[i].trimStart().startsWith(">")) {
            val body = mutableListOf<String>()
            while (i < lines.size && lines[i].trimStart().startsWith(">")) {
                body += unquote(lines[i])
                i++
            }
            blocks += NoteBlock.Quote(parseNotes(body.joinToString("\n")))
            continue
        }
        if (ruleRegex.matches(lines[i])) {
            blocks += NoteBlock.Rule
            i++
            continue
        }
        val heading = headingRegex.matchEntire(lines[i])
        if (heading != null) {
            blocks += NoteBlock.Heading(heading.groupValues[1].length, parseInlines(heading.groupValues[2]))
            i++
            continue
        }
        val paragraph = mutableListOf(lines[i].trim())
        i++
        while (i < lines.size && !startsNewBlock(lines, i)) {
            paragraph += lines[i].trim()
            i++
        }
        val text = paragraph.joinToString(" ")
        val box = checkboxRegex.matchEntire(text)
        if (box != null) {
            blocks += NoteBlock.Bullets(
                listOf(NoteListItem(box.groupValues[1].lowercase() == "x", parseInlines(box.groupValues[2]))),
            )
        } else {
            blocks += NoteBlock.Paragraph(parseInlines(text))
        }
    }
    return blocks
}

private data class Fence(val marker: Char, val length: Int)

private fun fenceOf(line: String): Fence? {
    val match = fenceRegex.matchEntire(line) ?: return null
    val token = match.groupValues[1]
    return Fence(token[0], token.length)
}

private fun closesFence(line: String, open: Fence): Boolean {
    val match = fenceRegex.matchEntire(line) ?: return false
    val token = match.groupValues[1]
    return token[0] == open.marker && token.length >= open.length && match.groupValues[2].isBlank()
}

private fun isListLine(line: String) = listRegex.matches(line)

private fun startsNewBlock(lines: List<String>, index: Int): Boolean {
    val line = lines[index]
    if (line.isBlank()) return true
    return fenceOf(line) != null ||
        isTableStart(lines, index) ||
        isListLine(line) ||
        line.trimStart().startsWith(">") ||
        ruleRegex.matches(line) ||
        headingRegex.matches(line)
}

private fun unquote(line: String): String {
    val trimmed = line.trimStart().removePrefix(">")
    return if (trimmed.startsWith(" ")) trimmed.drop(1) else trimmed
}

private fun parseList(lines: List<String>, start: Int): Pair<NoteBlock, Int> {
    val items = mutableListOf<NoteListItem>()
    var ordered: Boolean? = null
    var i = start
    while (i < lines.size) {
        if (lines[i].isBlank()) {
            val next = (i + 1 until lines.size).firstOrNull { lines[it].isNotBlank() } ?: break
            if (!isListLine(lines[next])) break
            i++
            continue
        }
        val match = listRegex.matchEntire(lines[i]) ?: break
        val marker = match.groupValues[2]
        val itemOrdered = marker[0].isDigit()
        if (ordered == null) ordered = itemOrdered
        if (ordered != itemOrdered) break
        val parts = mutableListOf(match.groupValues[3].trim())
        i++
        while (i < lines.size && lines[i].isNotBlank() && !isListLine(lines[i]) && lines[i].first().isWhitespace()) {
            parts += lines[i].trim()
            i++
        }
        val text = parts.joinToString(" ")
        val box = checkboxRegex.matchEntire(text)
        if (box != null) {
            items += NoteListItem(box.groupValues[1].lowercase() == "x", parseInlines(box.groupValues[2]))
        } else {
            items += NoteListItem(null, parseInlines(text))
        }
    }
    val block = if (ordered == true) NoteBlock.Numbered(items) else NoteBlock.Bullets(items)
    return block to i
}

private fun isTableStart(lines: List<String>, index: Int): Boolean {
    if (index + 1 >= lines.size || !lines[index].contains('|')) return false
    return isSeparator(lines[index + 1])
}

private fun isSeparator(line: String): Boolean {
    if (!line.contains('-')) return false
    val cells = splitRow(line)
    return cells.isNotEmpty() && cells.all { separatorCell.matches(it.replace(" ", "")) }
}

private fun splitRow(line: String): List<String> {
    var text = line.trim()
    if (text.startsWith("|")) text = text.substring(1)
    if (text.endsWith("|")) text = text.dropLast(1)
    return text.split('|').map { it.trim() }
}

private fun parseTable(lines: List<String>, start: Int): Pair<NoteBlock.Table, Int> {
    val header = splitRow(lines[start]).map { parseInlines(it) }
    var i = start + 2
    val rows = mutableListOf<List<List<NoteInline>>>()
    while (i < lines.size && lines[i].isNotBlank() && lines[i].contains('|')) {
        val cells = splitRow(lines[i]).map { parseInlines(it) }
        val padded = List(header.size) { index -> cells.getOrElse(index) { emptyList() } }
        rows += padded
        i++
    }
    return NoteBlock.Table(header, rows) to i
}

internal fun parseInlines(source: String): List<NoteInline> {
    val out = mutableListOf<NoteInline>()
    val buffer = StringBuilder()
    fun flush() {
        if (buffer.isNotEmpty()) {
            out += NoteInline.Text(buffer.toString())
            buffer.clear()
        }
    }
    var i = 0
    while (i < source.length) {
        if (source[i] == '\\' && i + 1 < source.length) {
            buffer.append(source[i + 1])
            i += 2
            continue
        }
        if (source.startsWith("~~", i)) {
            val close = source.indexOf("~~", i + 2)
            if (close > i) {
                flush()
                out += NoteInline.Strike(parseInlines(source.substring(i + 2, close)))
                i = close + 2
                continue
            }
        }
        if (source.startsWith("**", i) || source.startsWith("__", i)) {
            val marker = source.substring(i, i + 2)
            if (marker != "__" || canOpenUnderscore(source, i)) {
                val close = findCloser(source, i + 2, marker)
                if (close != null) {
                    flush()
                    out += NoteInline.Strong(parseInlines(source.substring(i + 2, close)))
                    i = close + 2
                    continue
                }
            }
        }
        if (source[i] == '`') {
            val close = source.indexOf('`', i + 1)
            if (close > i) {
                flush()
                out += NoteInline.Code(source.substring(i + 1, close))
                i = close + 1
                continue
            }
        }
        if (source[i] == '!' && i + 1 < source.length && source[i + 1] == '[') {
            val link = parseLink(source, i + 1)
            if (link != null) {
                flush()
                out += link.first
                i = link.second
                continue
            }
        }
        if (source[i] == '[') {
            val link = parseLink(source, i)
            if (link != null) {
                flush()
                out += link.first
                i = link.second
                continue
            }
        }
        if (source[i] == '*' || source[i] == '_') {
            val marker = source[i].toString()
            if (marker != "_" || canOpenUnderscore(source, i)) {
                val close = findCloser(source, i + 1, marker)
                if (close != null && (marker != "_" || canCloseUnderscore(source, close))) {
                    flush()
                    out += NoteInline.Emphasis(parseInlines(source.substring(i + 1, close)))
                    i = close + 1
                    continue
                }
            }
        }
        buffer.append(source[i])
        i++
    }
    flush()
    return out
}

private fun parseLink(source: String, start: Int): Pair<NoteInline, Int>? {
    val labelEnd = indexOf(source, ']', start + 1) ?: return null
    if (labelEnd + 1 >= source.length || source[labelEnd + 1] != '(') return null
    val urlEnd = indexOf(source, ')', labelEnd + 2) ?: return null
    val label = source.substring(start + 1, labelEnd)
    val url = source.substring(labelEnd + 2, urlEnd).trim()
    val children = parseInlines(label).ifEmpty { listOf(NoteInline.Text(url)) }
    val inline = if (isSafeUrl(url)) NoteInline.Link(children, url) else NoteInline.Text(plainText(children))
    return inline to urlEnd + 1
}

private fun isSafeUrl(url: String): Boolean {
    val lower = url.lowercase()
    return lower.startsWith("https://") || lower.startsWith("http://") || lower.startsWith("mailto:")
}

private fun plainText(inlines: List<NoteInline>): String = buildString {
    inlines.forEach { inline ->
        when (inline) {
            is NoteInline.Text -> append(inline.text)
            is NoteInline.Code -> append(inline.text)
            is NoteInline.Strong -> append(plainText(inline.children))
            is NoteInline.Emphasis -> append(plainText(inline.children))
            is NoteInline.Strike -> append(plainText(inline.children))
            is NoteInline.Link -> append(plainText(inline.children))
        }
    }
}

private fun findCloser(source: String, from: Int, marker: String): Int? {
    var index = from
    while (index < source.length) {
        if (source.startsWith(marker, index)) {
            if (marker.length == 1 && index + 1 < source.length && source[index + 1] == marker[0]) {
                index += 2
                continue
            }
            return index
        }
        index++
    }
    return null
}

private fun canOpenUnderscore(source: String, index: Int): Boolean {
    val previous = source.getOrNull(index - 1)
    return previous == null || !previous.isLetterOrDigit()
}

private fun canCloseUnderscore(source: String, index: Int): Boolean {
    val next = source.getOrNull(index + 1)
    return next == null || !next.isLetterOrDigit()
}

private fun indexOf(source: String, target: Char, from: Int): Int? {
    val found = source.indexOf(target, from)
    return found.takeIf { it >= 0 }
}

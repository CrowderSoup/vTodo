package com.crowdersoup.vtodo.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.LinkAnnotation
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.withLink
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.crowdersoup.vtodo.today.NoteBlock
import com.crowdersoup.vtodo.today.NoteInline
import com.crowdersoup.vtodo.today.NoteListItem
import com.crowdersoup.vtodo.today.parseNotes

@Composable
fun NotesView(markdown: String, modifier: Modifier = Modifier) {
    val blocks = remember(markdown) { parseNotes(markdown) }
    SelectionContainer(modifier) {
        Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            blocks.forEach { block -> NoteBlockView(block) }
        }
    }
}

@Composable
private fun NoteBlockView(block: NoteBlock) {
    when (block) {
        is NoteBlock.Heading -> Text(
            text = inlinesText(block.inlines),
            style = when (block.level) {
                1 -> MaterialTheme.typography.headlineSmall
                2 -> MaterialTheme.typography.titleLarge
                else -> MaterialTheme.typography.titleMedium
            },
        )
        is NoteBlock.Paragraph -> Text(
            text = inlinesText(block.inlines),
            style = MaterialTheme.typography.bodyLarge,
        )
        is NoteBlock.Bullets -> ListBlock(block.items, numbered = false)
        is NoteBlock.Numbered -> ListBlock(block.items, numbered = true)
        is NoteBlock.Quote -> Row(modifier = Modifier.height(IntrinsicSize.Min)) {
            Box(
                modifier = Modifier
                    .padding(vertical = 2.dp)
                    .width(3.dp)
                    .fillMaxHeight()
                    .clip(RoundedCornerShape(2.dp))
                    .background(MaterialTheme.colorScheme.primary),
            )
            Column(
                modifier = Modifier.padding(start = 12.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                block.blocks.forEach { NoteBlockView(it) }
            }
        }
        is NoteBlock.Code -> Text(
            text = block.text,
            style = MaterialTheme.typography.bodyMedium.copy(fontFamily = FontFamily.Monospace),
            modifier = Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(12.dp))
                .background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.65f))
                .padding(12.dp),
        )
        NoteBlock.Rule -> HorizontalDivider(color = MaterialTheme.colorScheme.outline.copy(alpha = 0.4f))
        is NoteBlock.Table -> TableBlock(block)
    }
}

@Composable
private fun ListBlock(items: List<NoteListItem>, numbered: Boolean) {
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        items.forEachIndexed { index, item ->
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                if (item.checked != null) {
                    CheckMark(item.checked)
                } else {
                    Text(
                        text = if (numbered) "${index + 1}." else "•",
                        style = MaterialTheme.typography.bodyLarge,
                        modifier = Modifier.width(if (numbered) 24.dp else 16.dp),
                    )
                }
                val style = if (item.checked == true) {
                    MaterialTheme.typography.bodyLarge.copy(
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        textDecoration = TextDecoration.LineThrough,
                    )
                } else {
                    MaterialTheme.typography.bodyLarge
                }
                Text(text = inlinesText(item.inlines), style = style, modifier = Modifier.weight(1f))
            }
        }
    }
}

@Composable
private fun CheckMark(checked: Boolean) {
    val tint = if (checked) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.outline
    Box(
        modifier = Modifier
            .padding(top = 3.dp)
            .size(16.dp)
            .clip(RoundedCornerShape(4.dp))
            .background(if (checked) tint else Color.Transparent)
            .border(1.5.dp, tint, RoundedCornerShape(4.dp)),
        contentAlignment = Alignment.Center,
    ) {
        if (checked) {
            Text(text = "✓", color = MaterialTheme.colorScheme.onPrimary, fontSize = 11.sp)
        }
    }
}

@Composable
private fun TableBlock(table: NoteBlock.Table) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .border(1.dp, MaterialTheme.colorScheme.outline.copy(alpha = 0.4f), RoundedCornerShape(12.dp)),
    ) {
        TableRow(table.header, header = true)
        table.rows.forEach { row ->
            HorizontalDivider(color = MaterialTheme.colorScheme.outline.copy(alpha = 0.3f))
            TableRow(row, header = false)
        }
    }
}

@Composable
private fun TableRow(cells: List<List<NoteInline>>, header: Boolean) {
    Row(modifier = Modifier.fillMaxWidth()) {
        cells.forEach { cell ->
            Text(
                text = inlinesText(cell),
                style = if (header) {
                    MaterialTheme.typography.labelLarge
                } else {
                    MaterialTheme.typography.bodyMedium
                },
                modifier = Modifier
                    .weight(1f)
                    .padding(horizontal = 10.dp, vertical = 8.dp),
            )
        }
    }
}

@Composable
private fun inlinesText(inlines: List<NoteInline>): AnnotatedString {
    val link = MaterialTheme.colorScheme.primary
    val code = MaterialTheme.colorScheme.surfaceVariant
    return buildAnnotatedString { appendInlines(inlines, link, code) }
}

private fun AnnotatedString.Builder.appendInlines(inlines: List<NoteInline>, link: Color, code: Color) {
    inlines.forEach { inline ->
        when (inline) {
            is NoteInline.Text -> append(inline.text)
            is NoteInline.Strong -> withStyle(SpanStyle(fontWeight = FontWeight.Bold)) {
                appendInlines(inline.children, link, code)
            }
            is NoteInline.Emphasis -> withStyle(SpanStyle(fontStyle = FontStyle.Italic)) {
                appendInlines(inline.children, link, code)
            }
            is NoteInline.Strike -> withStyle(SpanStyle(textDecoration = TextDecoration.LineThrough)) {
                appendInlines(inline.children, link, code)
            }
            is NoteInline.Code -> withStyle(
                SpanStyle(
                    fontFamily = FontFamily.Monospace,
                    background = code,
                ),
            ) { append(inline.text) }
            is NoteInline.Link -> withLink(LinkAnnotation.Url(inline.url)) {
                withStyle(
                    SpanStyle(color = link, textDecoration = TextDecoration.Underline),
                ) { appendInlines(inline.children, link, code) }
            }
        }
    }
}

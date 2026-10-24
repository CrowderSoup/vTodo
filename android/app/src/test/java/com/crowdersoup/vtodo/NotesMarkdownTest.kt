package com.crowdersoup.vtodo

import com.crowdersoup.vtodo.today.NoteBlock
import com.crowdersoup.vtodo.today.NoteInline
import com.crowdersoup.vtodo.today.parseNotes
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class NotesMarkdownTest {
    @Test
    fun rendersEmphasisCodeAndSafeLinks() {
        val paragraph = parseNotes(
            "Ship **the build** with *notes*, `code`, and [the site](https://example.com).",
        ).single() as NoteBlock.Paragraph

        assertTrue(paragraph.inlines[0] is NoteInline.Text)
        assertEquals(listOf(NoteInline.Text("the build")), (paragraph.inlines[1] as NoteInline.Strong).children)
        assertEquals(listOf(NoteInline.Text("notes")), (paragraph.inlines[3] as NoteInline.Emphasis).children)
        assertEquals("code", (paragraph.inlines[5] as NoteInline.Code).text)
        val link = paragraph.inlines[7] as NoteInline.Link
        assertEquals("https://example.com", link.url)
    }

    @Test
    fun dropsUnsafeLinksAndKeepsSnakeCase() {
        val paragraph = parseNotes("Keep task_id and [skip](javascript:alert(1)).").single() as NoteBlock.Paragraph
        val text = paragraph.inlines.filterIsInstance<NoteInline.Text>().joinToString("") { it.text }
        assertTrue(text.contains("task_id"))
        assertTrue(text.contains("skip"))
        assertTrue(paragraph.inlines.none { it is NoteInline.Link })
    }

    @Test
    fun rendersListsCheckboxesFenceQuoteAndTable() {
        val blocks = parseNotes(
            """
            # Today

            - [x] Ship polish
            - [ ] Follow up

            [ ] Share the board

            ```
            val x = 1
            ```

            > A quote

            | Task | Owner |
            | --- | --- |
            | Notes | Ada |

            ---
            """.trimIndent(),
        )

        assertEquals(1, (blocks[0] as NoteBlock.Heading).level)
        val list = blocks[1] as NoteBlock.Bullets
        assertEquals(true, list.items[0].checked)
        assertEquals(false, list.items[1].checked)
        assertEquals(false, (blocks[2] as NoteBlock.Bullets).items.single().checked)
        assertEquals("val x = 1", (blocks[3] as NoteBlock.Code).text)
        assertTrue((blocks[4] as NoteBlock.Quote).blocks.single() is NoteBlock.Paragraph)
        val table = blocks[5] as NoteBlock.Table
        assertEquals("Task", (table.header[0].single() as NoteInline.Text).text)
        assertEquals("Ada", (table.rows.single()[1].single() as NoteInline.Text).text)
        assertTrue(blocks[6] is NoteBlock.Rule)
    }
}

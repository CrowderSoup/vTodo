package com.crowdersoup.vtodo

import com.crowdersoup.vtodo.today.OpenTasks
import com.crowdersoup.vtodo.today.StatusRecord
import com.crowdersoup.vtodo.today.TaskRecord
import com.crowdersoup.vtodo.today.TodayTask
import com.crowdersoup.vtodo.today.TodayTasks
import com.crowdersoup.vtodo.today.addTags
import com.crowdersoup.vtodo.today.dueLabel
import com.crowdersoup.vtodo.today.formatDueTime
import com.crowdersoup.vtodo.today.normalizeRecurrenceFrom
import com.crowdersoup.vtodo.today.normalizeTags
import com.crowdersoup.vtodo.today.tagSuggestions
import com.crowdersoup.vtodo.today.openDateLabel
import com.crowdersoup.vtodo.today.parseDueInput
import com.crowdersoup.vtodo.today.parseRecurrenceDays
import com.crowdersoup.vtodo.today.recurrenceLabel
import com.crowdersoup.vtodo.today.statusColorArgb
import org.junit.Assert.assertEquals
import org.junit.Test
import java.time.LocalDate
import java.time.LocalTime
import java.util.Locale

class TodayTasksTest {
    private val today = LocalDate.of(2026, 10, 23)

    @Test
    fun selectKeepsOpenTasksDueTodayOrEarlier() {
        val tasks = listOf(
            record(1, "Tomorrow", dueDate = "2026-10-24"),
            record(2, "Undated", dueDate = null),
            record(3, "Archived", dueDate = "2026-10-23", isArchived = true),
            record(4, "Finished", dueDate = "2026-10-23", completedAt = "2026-10-23T12:00:00Z"),
            record(5, "Done status", dueDate = "2026-10-23", status = "done"),
            record(6, "Overdue", dueDate = "2026-10-21", sortOrder = 2),
            record(7, "Today all day", dueDate = "2026-10-23", sortOrder = 5),
            record(8, "Today 9am", dueDate = "2026-10-23", dueTime = "09:00:00", sortOrder = 1),
            record(9, "Today 3pm", dueDate = "2026-10-23", dueTime = "15:00:00", sortOrder = 0),
            record(10, "Bad date", dueDate = "next week"),
        )

        val selected = TodayTasks.select(
            tasks,
            listOf(StatusRecord("todo", "To Do", 0, false), StatusRecord("done", "Done", 1, true, "#336699")),
            today,
        )

        assertEquals(listOf(6L, 7L, 8L, 9L), selected.map { it.id })
        assertEquals(LocalTime.of(9, 0), selected[2].dueTime)
    }

    @Test
    fun dueLabelUsesOverdueDateAndTodayClock() {
        val overdue = TodayTask(1, "Pay rent", LocalDate.of(2026, 10, 21), null, 0)
        val timed = TodayTask(2, "Standup", today, LocalTime.of(9, 30), 0)

        assertEquals("Overdue · Oct 21", dueLabel(overdue, today, Locale.US))
        assertEquals("Today · 9:30 AM", dueLabel(timed, today, Locale.US))
    }

    @Test
    fun selectOpenKeepsUndatedAndFutureTasks() {
        val statuses = listOf(
            StatusRecord("backlog", "Backlog", 0, false, "#112233"),
            StatusRecord("todo", "To Do", 1, false),
            StatusRecord("done", "Done", 2, true),
        )
        val tasks = listOf(
            record(1, "Later", dueDate = "2026-10-24", status = "backlog", sortOrder = 3),
            record(2, "Undated", dueDate = null, sortOrder = 1),
            record(3, "Done", dueDate = "2026-10-20", status = "done"),
            record(4, "Archived", dueDate = "2026-10-22", isArchived = true),
            record(5, "Finished", dueDate = "2026-10-22", completedAt = "2026-10-22T00:00:00Z"),
            record(6, "Overdue", dueDate = "2026-10-21", dueTime = "09:00:00", sortOrder = 4, tags = listOf("home")),
            record(7, "Bad date", dueDate = "next week", sortOrder = 2),
        )

        val selected = OpenTasks.select(tasks, statuses)

        assertEquals(listOf(6L, 1L, 2L, 7L), selected.map { it.id })
        assertEquals("Backlog", selected[1].statusName)
        assertEquals("#112233", selected[1].statusColor)
        assertEquals(listOf("home"), selected[0].tags)
        assertEquals(null, selected[2].dueDate)
        assertEquals("Overdue · Oct 21 · 9:00 AM", openDateLabel(selected[0], today, Locale.US))
        assertEquals(null, openDateLabel(selected[3], today, Locale.US))
    }

    @Test
    fun normalizeTagsTrimsAndDropsBlanks() {
        assertEquals(listOf("home", "errands", "a", "b"), normalizeTags(listOf(" home ", "", "errands", "home", "a, b")))
        assertEquals(0xFF336699L, statusColorArgb(" #336699 "))
        assertEquals(null, statusColorArgb("blue"))
    }

    @Test
    fun tagSuggestionsStayShortAndFollowWhatWasTyped() {
        val known = listOf("home", "errands", "Health", "hobby", "h1", "h2", "h3", "h4", "h5", "h6")

        assertEquals(
            listOf("home", "errands", "Health", "hobby", "h1", "h2", "h3", "h4"),
            tagSuggestions(known, emptyList(), ""),
        )
        assertEquals(
            listOf("home", "hobby", "h1", "h2", "h3", "h4", "h5", "h6"),
            tagSuggestions(known, listOf("Health"), "h"),
        )
        assertEquals(listOf("Health"), tagSuggestions(known, emptyList(), "HEALTH"))
        assertEquals(emptyList<String>(), tagSuggestions(known, listOf("home"), "zzz"))
    }

    @Test
    fun addTagsSkipsBlanksAndCaseDuplicates() {
        assertEquals(listOf("home", "errands"), addTags(listOf("home"), " errands, home, Home "))
        assertEquals(listOf("home"), addTags(listOf("home"), " "))
    }

    @Test
    fun parseDueInputAcceptsBlankAndIsoDates() {
        assertEquals(null, parseDueInput("  ").getOrThrow())
        assertEquals(LocalDate.of(2026, 10, 24), parseDueInput("2026-10-24").getOrThrow())
        assertEquals(true, parseDueInput("Oct 24").isFailure)
    }

    @Test
    fun recurrenceLabelUsesDayOrDays() {
        assertEquals("Repeats every 1 day", recurrenceLabel(1))
        assertEquals("Repeats every 7 days", recurrenceLabel(7))
    }

    @Test
    fun parseRecurrenceDaysAcceptsBlankAndWholeDays() {
        assertEquals(null, parseRecurrenceDays(" ").getOrThrow())
        assertEquals(7, parseRecurrenceDays(" 7 ").getOrThrow())
        assertEquals(32_767, parseRecurrenceDays("32767").getOrThrow())
        assertEquals(true, parseRecurrenceDays("0").isFailure)
        assertEquals(true, parseRecurrenceDays("weekly").isFailure)
        assertEquals(true, parseRecurrenceDays("32768").isFailure)
    }

    @Test
    fun formatDueTimeUsesHourAndMinute() {
        assertEquals("09:30", formatDueTime(LocalTime.of(9, 30, 15)))
        assertEquals("00:05", formatDueTime(LocalTime.of(0, 5)))
    }

    @Test
    fun normalizeRecurrenceFromKeepsTheTwoServerValues() {
        assertEquals("due_date", normalizeRecurrenceFrom("due_date"))
        assertEquals("completion", normalizeRecurrenceFrom("completion"))
        assertEquals("completion", normalizeRecurrenceFrom("next_tuesday"))
    }

    @Test
    fun selectKeepsRecurrenceOnOpenAndTodayTasks() {
        val task = record(
            1,
            "Weekly",
            dueDate = "2026-10-23",
            recurrenceDays = 7,
            recurrenceFrom = "due_date",
        )
        val statuses = listOf(StatusRecord("todo", "To Do", 0, false))

        val todayTask = TodayTasks.select(listOf(task), statuses, today).single()
        val openTask = OpenTasks.select(listOf(task), statuses).single()

        assertEquals(7, todayTask.recurrenceDays)
        assertEquals(7, openTask.recurrenceDays)
        assertEquals("due_date", openTask.recurrenceFrom)
    }

    private fun record(
        id: Long,
        title: String,
        dueDate: String?,
        dueTime: String? = null,
        status: String = "todo",
        isArchived: Boolean = false,
        completedAt: String? = null,
        sortOrder: Int = 0,
        tags: List<String> = emptyList(),
        recurrenceDays: Int? = null,
        recurrenceFrom: String = "completion",
    ) = TaskRecord(
        id,
        title,
        status,
        dueDate,
        dueTime,
        isArchived,
        completedAt,
        sortOrder,
        tags = tags,
        recurrenceDays = recurrenceDays,
        recurrenceFrom = recurrenceFrom,
    )
}

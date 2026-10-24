package com.crowdersoup.vtodo

import com.crowdersoup.vtodo.today.OpenTasks
import com.crowdersoup.vtodo.today.StatusRecord
import com.crowdersoup.vtodo.today.TaskRecord
import com.crowdersoup.vtodo.today.TodayTask
import com.crowdersoup.vtodo.today.TodayTasks
import com.crowdersoup.vtodo.today.dueLabel
import com.crowdersoup.vtodo.today.openLabel
import com.crowdersoup.vtodo.today.parseDueInput
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

        val selected = TodayTasks.select(tasks, doneSlugs = setOf("done"), today = today)

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
            StatusRecord("backlog", "Backlog", 0, false),
            StatusRecord("todo", "To Do", 1, false),
            StatusRecord("done", "Done", 2, true),
        )
        val tasks = listOf(
            record(1, "Later", dueDate = "2026-10-24", status = "backlog", sortOrder = 3),
            record(2, "Undated", dueDate = null, sortOrder = 1),
            record(3, "Done", dueDate = "2026-10-20", status = "done"),
            record(4, "Archived", dueDate = "2026-10-22", isArchived = true),
            record(5, "Finished", dueDate = "2026-10-22", completedAt = "2026-10-22T00:00:00Z"),
            record(6, "Overdue", dueDate = "2026-10-21", dueTime = "09:00:00", sortOrder = 4),
            record(7, "Bad date", dueDate = "next week", sortOrder = 2),
        )

        val selected = OpenTasks.select(tasks, statuses)

        assertEquals(listOf(6L, 1L, 2L, 7L), selected.map { it.id })
        assertEquals("Backlog", selected[1].statusName)
        assertEquals(null, selected[2].dueDate)
        assertEquals("To Do · Overdue · Oct 21 · 9:00 AM", openLabel(selected[0], today, Locale.US))
        assertEquals("To Do · No date", openLabel(selected[3], today, Locale.US))
    }

    @Test
    fun parseDueInputAcceptsBlankAndIsoDates() {
        assertEquals(null, parseDueInput("  ").getOrThrow())
        assertEquals(LocalDate.of(2026, 10, 24), parseDueInput("2026-10-24").getOrThrow())
        assertEquals(true, parseDueInput("Oct 24").isFailure)
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
    ) = TaskRecord(id, title, status, dueDate, dueTime, isArchived, completedAt, sortOrder)
}

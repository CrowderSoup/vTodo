package com.crowdersoup.vtodo

import com.crowdersoup.vtodo.today.TaskRecord
import com.crowdersoup.vtodo.today.TodayTask
import com.crowdersoup.vtodo.today.TodayTasks
import com.crowdersoup.vtodo.today.dueLabel
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

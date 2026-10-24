package com.crowdersoup.vtodo.today

import java.time.LocalDate
import java.time.LocalTime
import java.time.format.DateTimeFormatter
import java.util.Locale

data class TaskRecord(
    val id: Long,
    val title: String,
    val status: String,
    val dueDate: String?,
    val dueTime: String?,
    val isArchived: Boolean,
    val completedAt: String?,
    val sortOrder: Int,
)

data class TodayTask(
    val id: Long,
    val title: String,
    val dueDate: LocalDate,
    val dueTime: LocalTime?,
    val sortOrder: Int,
)

object TodayTasks {
    fun select(tasks: List<TaskRecord>, doneSlugs: Set<String>, today: LocalDate): List<TodayTask> {
        return tasks.mapNotNull { task -> toTodayTask(task, doneSlugs, today) }
            .sortedWith(
                compareBy<TodayTask> { it.dueDate }
                    .thenBy { it.dueTime != null }
                    .thenBy { it.dueTime ?: LocalTime.MIN }
                    .thenBy { it.sortOrder }
                    .thenBy { it.id },
            )
    }

    private fun toTodayTask(task: TaskRecord, doneSlugs: Set<String>, today: LocalDate): TodayTask? {
        if (task.isArchived || !task.completedAt.isNullOrBlank() || task.status in doneSlugs) {
            return null
        }
        val due = task.dueDate?.let { runCatching { LocalDate.parse(it) }.getOrNull() } ?: return null
        if (due > today) return null
        val time = task.dueTime?.takeIf { it.isNotBlank() }?.let {
            runCatching { LocalTime.parse(it) }.getOrNull()
        }
        return TodayTask(
            id = task.id,
            title = task.title,
            dueDate = due,
            dueTime = time,
            sortOrder = task.sortOrder,
        )
    }
}

fun dueLabel(task: TodayTask, today: LocalDate, locale: Locale): String {
    val day = if (task.dueDate < today) {
        "Overdue · " + task.dueDate.format(DateTimeFormatter.ofPattern("MMM d", locale))
    } else {
        "Today"
    }
    val clock = task.dueTime?.format(DateTimeFormatter.ofPattern("h:mm a", locale))
    return if (clock == null) day else "$day · $clock"
}

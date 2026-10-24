package com.crowdersoup.vtodo.data

import androidx.room.withTransaction
import com.crowdersoup.vtodo.today.OpenTask
import com.crowdersoup.vtodo.today.OpenTasks
import com.crowdersoup.vtodo.today.StatusRecord
import com.crowdersoup.vtodo.today.TodayTask
import com.crowdersoup.vtodo.today.TodayTasks
import com.crowdersoup.vtodo.today.normalizeTags
import java.time.LocalDate
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.time.Instant
import kotlin.coroutines.cancellation.CancellationException

data class TaskLists(
    val today: List<TodayTask> = emptyList(),
    val open: List<OpenTask> = emptyList(),
    val statuses: List<StatusRecord> = emptyList(),
)

class VtodoRepository(
    private val database: VtodoDatabase,
    private val api: VtodoApi,
    private val sessionStore: SessionStore,
) {
    private val mutex = Mutex()

    fun observeLists(): Flow<TaskLists> {
        return combine(database.taskDao().observe(), database.statusDao().observe()) { tasks, statuses ->
            val records = tasks.map { it.toRecord() }
            val statusRecords = statuses.map { it.toRecord() }
            TaskLists(
                today = TodayTasks.select(records, statusRecords, LocalDate.now()),
                open = OpenTasks.select(records, statusRecords),
                statuses = statusRecords.sortedBy { it.sortOrder },
            )
        }
    }

    suspend fun todaySnapshot(today: LocalDate = LocalDate.now()): List<TodayTask> {
        val statuses = database.statusDao().all().map { it.toRecord() }
        return TodayTasks.select(database.taskDao().all().map { it.toRecord() }, statuses, today)
    }

    suspend fun findTask(id: Long): OpenTask? {
        val entity = database.taskDao().get(id) ?: return null
        if (entity.isArchived) return null
        return OpenTasks.from(entity.toRecord(), database.statusDao().all().map { it.toRecord() })
    }

    suspend fun signIn(baseUrl: String, token: String): Result<Unit> {
        val normalized = try {
            normalizeBaseUrl(baseUrl)
        } catch (e: IllegalArgumentException) {
            return Result.failure(e)
        }
        val trimmed = token.trim()
        if (trimmed.isEmpty()) {
            return Result.failure(IllegalArgumentException("API token is required."))
        }
        val session = Session(normalized, trimmed)
        return try {
            api.fetchStatuses(session)
            sessionStore.save(session)
            sync()
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    suspend fun sync(): Result<Unit> {
        val session = sessionStore.current()
            ?: return Result.failure(IllegalStateException("Sign in first."))
        return try {
            mutex.withLock { pull(session) }
            Result.success(Unit)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    suspend fun createTask(title: String, notes: String, dueDate: LocalDate?, tags: List<String>): Result<Unit> {
        val trimmed = title.trim()
        if (trimmed.isEmpty()) {
            return Result.failure(IllegalArgumentException("A title is required."))
        }
        val session = sessionStore.current()
            ?: return Result.failure(IllegalStateException("Sign in first."))
        return try {
            mutex.withLock {
                api.createTask(session, trimmed, notes.trim(), dueDate?.toString(), normalizeTags(tags))
                pull(session)
            }
            Result.success(Unit)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    suspend fun saveTask(
        taskId: Long,
        title: String,
        notes: String,
        dueDate: LocalDate?,
        tags: List<String>,
    ): Result<Unit> {
        val trimmed = title.trim()
        if (trimmed.isEmpty()) {
            return Result.failure(IllegalArgumentException("A title is required."))
        }
        val session = sessionStore.current()
            ?: return Result.failure(IllegalStateException("Sign in first."))
        return try {
            mutex.withLock {
                api.patchTask(session, taskId, trimmed, notes.trim(), dueDate?.toString(), normalizeTags(tags))
                pull(session)
            }
            Result.success(Unit)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    suspend fun complete(taskId: Long): Result<Unit> {
        val done = database.statusDao().all()
            .filter { it.isDone }
            .minByOrNull { it.sortOrder }
            ?: return Result.failure(IllegalStateException("Add a completed status on the website first."))
        return move(taskId, done.slug)
    }

    suspend fun move(taskId: Long, statusSlug: String): Result<Unit> {
        val session = sessionStore.current()
            ?: return Result.failure(IllegalStateException("Sign in first."))
        var previous: TaskEntity? = null
        return try {
            mutex.withLock {
                val status = database.statusDao().all().firstOrNull { it.slug == statusSlug }
                    ?: throw IllegalStateException("That status is not on this phone yet. Refresh and try again.")
                previous = database.taskDao().get(taskId)
                val existing = previous
                if (existing != null) {
                    val completedAt = if (status.isDone) {
                        existing.completedAt ?: Instant.now().toString()
                    } else {
                        null
                    }
                    database.taskDao().updateStatus(taskId, status.slug, completedAt)
                }
                api.moveTask(session, taskId, status.slug)
                pull(session)
            }
            Result.success(Unit)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            restore(taskId, previous)
            Result.failure(e)
        }
    }

    suspend fun signOut() {
        mutex.withLock {
            sessionStore.clear()
            database.withTransaction {
                database.taskDao().clear()
                database.statusDao().clear()
            }
        }
    }

    private suspend fun pull(session: Session) {
        val tasks = api.fetchTasks(session)
        val statuses = api.fetchStatuses(session)
        database.withTransaction {
            database.taskDao().clear()
            database.statusDao().clear()
            database.taskDao().insertAll(tasks.map { it.toEntity() })
            database.statusDao().insertAll(statuses.map { it.toEntity() })
        }
    }

    private suspend fun restore(taskId: Long, previous: TaskEntity?) {
        val session = sessionStore.current()
        if (session != null) {
            try {
                mutex.withLock { pull(session) }
                return
            } catch (_: Exception) {
                // The next sync replaces the table from the server.
            }
        }
        if (previous != null) {
            database.taskDao().updateStatus(taskId, previous.status, previous.completedAt)
        }
    }
}

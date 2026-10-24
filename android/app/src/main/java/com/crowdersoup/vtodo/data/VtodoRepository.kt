package com.crowdersoup.vtodo.data

import androidx.room.withTransaction
import com.crowdersoup.vtodo.today.TodayTask
import com.crowdersoup.vtodo.today.TodayTasks
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.time.Instant
import java.time.LocalDate
import kotlin.coroutines.cancellation.CancellationException

class VtodoRepository(
    private val database: VtodoDatabase,
    private val api: VtodoApi,
    private val sessionStore: SessionStore,
) {
    private val mutex = Mutex()

    fun observeToday(): Flow<List<TodayTask>> {
        return combine(database.taskDao().observe(), database.statusDao().observe()) { tasks, statuses ->
            TodayTasks.select(
                tasks.map { it.toRecord() },
                statuses.filter { it.isDone }.map { it.slug }.toSet(),
                LocalDate.now(),
            )
        }
    }

    suspend fun todaySnapshot(today: LocalDate = LocalDate.now()): List<TodayTask> {
        val done = database.statusDao().all().filter { it.isDone }.map { it.slug }.toSet()
        return TodayTasks.select(database.taskDao().all().map { it.toRecord() }, done, today)
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

    suspend fun complete(taskId: Long): Result<Unit> {
        val session = sessionStore.current()
            ?: return Result.failure(IllegalStateException("Sign in first."))
        return try {
            mutex.withLock {
                val done = database.statusDao().all()
                    .filter { it.isDone }
                    .minByOrNull { it.sortOrder }
                    ?: throw IllegalStateException("Add a completed status on the website first.")
                val existing = database.taskDao().get(taskId)
                if (existing != null && existing.completedAt.isNullOrBlank()) {
                    database.taskDao().setCompleted(taskId, Instant.now().toString())
                }
                api.moveTask(session, taskId, done.slug)
                pull(session)
            }
            Result.success(Unit)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            restore(taskId)
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

    private suspend fun restore(taskId: Long) {
        val session = sessionStore.current() ?: return
        try {
            mutex.withLock { pull(session) }
        } catch (_: Exception) {
            database.taskDao().setCompleted(taskId, null)
        }
    }
}

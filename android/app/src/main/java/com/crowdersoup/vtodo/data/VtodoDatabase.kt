package com.crowdersoup.vtodo.data

import androidx.room.Dao
import androidx.room.Database
import androidx.room.Entity
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.PrimaryKey
import androidx.room.Query
import androidx.room.RoomDatabase
import com.crowdersoup.vtodo.today.StatusRecord
import com.crowdersoup.vtodo.today.TaskRecord
import kotlinx.coroutines.flow.Flow
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.builtins.serializer
import kotlinx.serialization.json.Json

@Entity(tableName = "tasks")
data class TaskEntity(
    @PrimaryKey val id: Long,
    val title: String,
    val status: String,
    val dueDate: String?,
    val dueTime: String?,
    val isArchived: Boolean,
    val completedAt: String?,
    val sortOrder: Int,
    val notes: String,
    val tags: String,
)

@Entity(tableName = "statuses")
data class StatusEntity(
    @PrimaryKey val slug: String,
    val id: Long,
    val name: String,
    val sortOrder: Int,
    val isDone: Boolean,
    val color: String,
)

fun TaskDto.toEntity() = TaskEntity(
    id = id,
    title = title,
    status = status,
    dueDate = dueDate,
    dueTime = dueTime,
    isArchived = isArchived,
    completedAt = completedAt,
    sortOrder = order,
    notes = notes,
    tags = tagsToJson(tags),
)

fun TaskEntity.toRecord() = TaskRecord(
    id = id,
    title = title,
    status = status,
    dueDate = dueDate,
    dueTime = dueTime,
    isArchived = isArchived,
    completedAt = completedAt,
    sortOrder = sortOrder,
    notes = notes,
    tags = tagsFromJson(tags),
)

fun StatusDto.toEntity() = StatusEntity(
    slug = slug,
    id = id,
    name = name,
    sortOrder = order,
    isDone = isDone,
    color = color,
)

fun StatusEntity.toRecord() = StatusRecord(
    slug = slug,
    name = name,
    sortOrder = sortOrder,
    isDone = isDone,
    color = color,
)

@Dao
interface TaskDao {
    @Query("SELECT * FROM tasks")
    fun observe(): Flow<List<TaskEntity>>

    @Query("SELECT * FROM tasks")
    suspend fun all(): List<TaskEntity>

    @Query("SELECT * FROM tasks WHERE id = :id")
    suspend fun get(id: Long): TaskEntity?

    @Query("DELETE FROM tasks")
    suspend fun clear()

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertAll(tasks: List<TaskEntity>)

    @Query("UPDATE tasks SET completedAt = :completedAt WHERE id = :id")
    suspend fun setCompleted(id: Long, completedAt: String?)

    @Query("UPDATE tasks SET status = :status, completedAt = :completedAt WHERE id = :id")
    suspend fun updateStatus(id: Long, status: String, completedAt: String?)
}

@Dao
interface StatusDao {
    @Query("SELECT * FROM statuses")
    fun observe(): Flow<List<StatusEntity>>

    @Query("SELECT * FROM statuses")
    suspend fun all(): List<StatusEntity>

    @Query("DELETE FROM statuses")
    suspend fun clear()

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertAll(statuses: List<StatusEntity>)
}

private val tagJson = Json { ignoreUnknownKeys = true }
private val tagListSerializer = ListSerializer(String.serializer())

internal fun tagsToJson(tags: List<String>): String = tagJson.encodeToString(tagListSerializer, tags)

internal fun tagsFromJson(raw: String): List<String> {
    return runCatching { tagJson.decodeFromString(tagListSerializer, raw) }.getOrDefault(emptyList())
}

@Database(
    entities = [TaskEntity::class, StatusEntity::class],
    version = 3,
    exportSchema = false,
)
abstract class VtodoDatabase : RoomDatabase() {
    abstract fun taskDao(): TaskDao
    abstract fun statusDao(): StatusDao
}

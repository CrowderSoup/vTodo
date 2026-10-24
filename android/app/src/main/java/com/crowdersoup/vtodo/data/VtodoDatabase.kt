package com.crowdersoup.vtodo.data

import androidx.room.Dao
import androidx.room.Database
import androidx.room.Entity
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.PrimaryKey
import androidx.room.Query
import androidx.room.RoomDatabase
import com.crowdersoup.vtodo.today.TaskRecord
import kotlinx.coroutines.flow.Flow

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
)

@Entity(tableName = "statuses")
data class StatusEntity(
    @PrimaryKey val slug: String,
    val id: Long,
    val sortOrder: Int,
    val isDone: Boolean,
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
)

fun StatusDto.toEntity() = StatusEntity(
    slug = slug,
    id = id,
    sortOrder = order,
    isDone = isDone,
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

@Database(
    entities = [TaskEntity::class, StatusEntity::class],
    version = 1,
    exportSchema = false,
)
abstract class VtodoDatabase : RoomDatabase() {
    abstract fun taskDao(): TaskDao
    abstract fun statusDao(): StatusDao
}

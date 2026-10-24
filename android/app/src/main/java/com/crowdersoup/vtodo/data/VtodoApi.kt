package com.crowdersoup.vtodo.data

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException
import java.util.concurrent.TimeUnit

class VtodoApiException(val httpCode: Int?, message: String) : Exception(message)

@Serializable
data class TaskDto(
    val id: Long,
    val title: String,
    val status: String,
    @SerialName("due_date") val dueDate: String? = null,
    @SerialName("due_time") val dueTime: String? = null,
    @SerialName("is_archived") val isArchived: Boolean = false,
    @SerialName("completed_at") val completedAt: String? = null,
    val order: Int = 0,
    val notes: String = "",
)

@Serializable
data class StatusDto(
    val id: Long,
    val name: String = "",
    val slug: String,
    val order: Int = 0,
    @SerialName("is_done") val isDone: Boolean = false,
)

@Serializable
private data class MoveRequest(@SerialName("new_status") val newStatus: String)

@Serializable
private data class ErrorBody(val detail: String? = null)

class VtodoApi(
    private val client: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .writeTimeout(30, TimeUnit.SECONDS)
        .build(),
) {
    private val json = Json { ignoreUnknownKeys = true }
    private val jsonMedia = "application/json; charset=utf-8".toMediaType()

    suspend fun fetchTasks(session: Session): List<TaskDto> {
        val body = call(request(session, "/api/v1/tasks/").get().build())
        return decode(body)
    }

    suspend fun fetchStatuses(session: Session): List<StatusDto> {
        val body = call(request(session, "/api/v1/statuses/").get().build())
        return decode(body)
    }

    suspend fun createTask(session: Session, title: String, notes: String, dueDate: String?) {
        val payload = buildJsonObject {
            put("title", title)
            put("notes", notes)
            if (dueDate != null) put("due_date", dueDate)
        }
        call(
            request(session, "/api/v1/tasks/")
                .post(payload.toString().toRequestBody(jsonMedia))
                .build(),
        )
    }

    suspend fun patchTask(session: Session, taskId: Long, title: String, notes: String, dueDate: String?) {
        val payload = buildJsonObject {
            put("title", title)
            put("notes", notes)
            if (dueDate == null) put("due_date", JsonNull) else put("due_date", dueDate)
        }
        call(
            request(session, "/api/v1/tasks/$taskId/")
                .patch(payload.toString().toRequestBody(jsonMedia))
                .build(),
        )
    }

    suspend fun moveTask(session: Session, taskId: Long, newStatus: String) {
        val payload = json.encodeToString(MoveRequest(newStatus))
        call(
            request(session, "/api/v1/tasks/$taskId/move/")
                .post(payload.toRequestBody(jsonMedia))
                .build(),
        )
    }

    private fun request(session: Session, path: String): Request.Builder {
        return Request.Builder()
            .url(session.baseUrl + path)
            .header("Authorization", "Token ${session.token}")
            .header("Accept", "application/json")
            .header("User-Agent", "vtodo-android")
    }

    private suspend fun call(request: Request): String = withContext(Dispatchers.IO) {
        try {
            client.newCall(request).execute().use { response ->
                val body = response.body?.string().orEmpty()
                if (!response.isSuccessful) {
                    throw VtodoApiException(response.code, httpError(response.code, body))
                }
                body
            }
        } catch (e: VtodoApiException) {
            throw e
        } catch (_: IOException) {
            throw VtodoApiException(null, "Couldn't reach the server.")
        }
    }

    private inline fun <reified T> decode(body: String): T {
        try {
            return json.decodeFromString(body)
        } catch (_: SerializationException) {
            throw VtodoApiException(null, "The server sent a response the app didn't understand.")
        }
    }

    private fun httpError(code: Int, body: String): String {
        val detail = runCatching { json.decodeFromString<ErrorBody>(body).detail }
            .getOrNull()
            ?.takeIf { it.isNotBlank() }
        if (detail != null) return detail
        return when (code) {
            401, 403 -> "That token was rejected. Copy a new one from Settings, then API token."
            else -> "The server returned $code."
        }
    }
}

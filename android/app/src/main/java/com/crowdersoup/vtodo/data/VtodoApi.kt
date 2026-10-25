package com.crowdersoup.vtodo.data

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.add
import kotlinx.serialization.json.buildJsonArray
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
    val tags: List<String> = emptyList(),
    @SerialName("recurrence_days") val recurrenceDays: Int? = null,
    @SerialName("recurrence_from") val recurrenceFrom: String = "completion",
)

data class TaskBody(
    val title: String,
    val notes: String,
    val dueDate: String?,
    val dueTime: String?,
    val tags: List<String>,
    val recurrenceDays: Int?,
    val recurrenceFrom: String,
)

@Serializable
data class StatusDto(
    val id: Long,
    val name: String = "",
    val slug: String,
    val order: Int = 0,
    val color: String = "",
    @SerialName("is_done") val isDone: Boolean = false,
)

@Serializable
private data class MoveRequest(@SerialName("new_status") val newStatus: String)

@Serializable
private data class GoogleClientResponse(@SerialName("client_id") val clientId: String = "")

@Serializable
private data class GoogleExchangeRequest(@SerialName("id_token") val idToken: String)

@Serializable
private data class GoogleExchangeResponse(val token: String = "")

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

    suspend fun fetchGoogleClientId(baseUrl: String): String {
        val body = try {
            call(anonymous(baseUrl, "/api/v1/auth/google/").get().build())
        } catch (e: VtodoApiException) {
            throw googleSetupError(e)
        }
        val clientId = decode<GoogleClientResponse>(body).clientId
        if (clientId.isBlank()) {
            throw VtodoApiException(null, "Google sign-in is not configured on this server.")
        }
        return clientId
    }

    suspend fun exchangeGoogleIdToken(baseUrl: String, idToken: String): String {
        val payload = json.encodeToString(GoogleExchangeRequest(idToken))
        val body = try {
            call(
                anonymous(baseUrl, "/api/v1/auth/google/")
                    .post(payload.toRequestBody(jsonMedia))
                    .build(),
            )
        } catch (e: VtodoApiException) {
            throw googleSetupError(e)
        }
        val token = decode<GoogleExchangeResponse>(body).token
        if (token.isBlank()) {
            throw VtodoApiException(null, "The server didn't return an API token.")
        }
        return token
    }

    suspend fun createTask(session: Session, body: TaskBody) {
        call(
            request(session, "/api/v1/tasks/")
                .post(taskPayload(body, null).toString().toRequestBody(jsonMedia))
                .build(),
        )
    }

    suspend fun patchTask(session: Session, taskId: Long, changes: JsonObject) {
        call(
            request(session, "/api/v1/tasks/$taskId/")
                .patch(changes.toString().toRequestBody(jsonMedia))
                .build(),
        )
    }

    suspend fun deleteTask(session: Session, taskId: Long) {
        call(request(session, "/api/v1/tasks/$taskId/").delete().build())
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
        return anonymous(session.baseUrl, path)
            .header("Authorization", "Token ${session.token}")
    }

    private fun anonymous(baseUrl: String, path: String): Request.Builder {
        return Request.Builder()
            .url(baseUrl + path)
            .header("Accept", "application/json")
            .header("User-Agent", "vtodo-android")
    }

    private fun googleSetupError(error: VtodoApiException): VtodoApiException {
        if (error.httpCode == 404) {
            return VtodoApiException(
                404,
                "This server does not support Google sign-in yet. Update it, or paste an API token.",
            )
        }
        return error
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

/**
 * The JSON for a task write. With [before], only the fields that differ from
 * it are included, so a PATCH from an edit started on an older copy of the
 * task leaves alone whatever someone changed on the website since.
 */
internal fun taskPayload(after: TaskBody, before: TaskBody?) = buildJsonObject {
    fun changed(pick: (TaskBody) -> Any?) = before == null || pick(before) != pick(after)
    val dueTime = if (after.dueDate == null) null else after.dueTime
    val beforeTime = before?.let { if (it.dueDate == null) null else it.dueTime }
    if (changed { it.title }) put("title", after.title)
    if (changed { it.notes }) put("notes", after.notes)
    if (changed { it.dueDate }) put("due_date", after.dueDate?.let { JsonPrimitive(it) } ?: JsonNull)
    if (before == null || beforeTime != dueTime) put("due_time", dueTime?.let { JsonPrimitive(it) } ?: JsonNull)
    if (changed { it.tags }) put("tags", buildJsonArray { after.tags.forEach { add(it) } })
    if (changed { it.recurrenceDays }) {
        put("recurrence_days", after.recurrenceDays?.let { JsonPrimitive(it) } ?: JsonNull)
    }
    if (changed { it.recurrenceFrom }) put("recurrence_from", after.recurrenceFrom)
}

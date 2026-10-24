package com.crowdersoup.vtodo.data

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow

data class Session(val baseUrl: String, val token: String)

class SessionStore(context: Context) {
    private val prefs: SharedPreferences = encryptedPrefs(context)
    private val state = MutableStateFlow(read())
    val session: StateFlow<Session?> = state

    fun current(): Session? = state.value

    fun save(session: Session) {
        prefs.edit()
            .putString(KEY_URL, session.baseUrl)
            .putString(KEY_TOKEN, session.token)
            .apply()
        state.value = session
    }

    fun clear() {
        prefs.edit().remove(KEY_URL).remove(KEY_TOKEN).apply()
        state.value = null
    }

    private fun read(): Session? {
        val url = prefs.getString(KEY_URL, null)?.takeIf { it.isNotBlank() } ?: return null
        val token = prefs.getString(KEY_TOKEN, null)?.takeIf { it.isNotBlank() } ?: return null
        return Session(url, token)
    }

    private fun encryptedPrefs(context: Context): SharedPreferences {
        val masterKey = MasterKey.Builder(context)
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build()
        return EncryptedSharedPreferences.create(
            context,
            FILE_NAME,
            masterKey,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
        )
    }

    private companion object {
        const val FILE_NAME = "vtodo_session"
        const val KEY_URL = "base_url"
        const val KEY_TOKEN = "token"
    }
}

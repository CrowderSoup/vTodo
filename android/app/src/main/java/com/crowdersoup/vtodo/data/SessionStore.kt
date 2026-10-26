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
    private val reason = MutableStateFlow(prefs.getString(KEY_SIGNED_OUT_REASON, null))

    /**
     * Why the phone was signed out when it wasn't the person's doing (the
     * server rejected the token). Kept on disk because that usually happens
     * in a background sync, with nobody looking at the app.
     */
    val signedOutReason: StateFlow<String?> = reason

    fun current(): Session? = state.value

    fun save(session: Session) {
        prefs.edit()
            .putString(KEY_URL, session.baseUrl)
            .putString(KEY_TOKEN, session.token)
            .remove(KEY_SIGNED_OUT_REASON)
            .apply()
        reason.value = null
        state.value = session
    }

    fun clear(signedOutReason: String? = null) {
        prefs.edit()
            .remove(KEY_URL)
            .remove(KEY_TOKEN)
            .putString(KEY_SIGNED_OUT_REASON, signedOutReason)
            .apply()
        reason.value = signedOutReason
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
        const val KEY_SIGNED_OUT_REASON = "signed_out_reason"
    }
}

package com.crowdersoup.vtodo.data

import android.app.Activity
import android.util.Log
import androidx.credentials.CredentialManager
import androidx.credentials.GetCredentialRequest
import com.google.android.libraries.identity.googleid.GetSignInWithGoogleOption
import com.google.android.libraries.identity.googleid.GoogleIdTokenCredential
import kotlin.coroutines.cancellation.CancellationException

object GoogleSignIn {
    suspend fun requestIdToken(activity: Activity, serverClientId: String): String {
        val option = GetSignInWithGoogleOption.Builder(serverClientId).build()
        val request = GetCredentialRequest.Builder()
            .addCredentialOption(option)
            .build()
        val result = try {
            CredentialManager.create(activity).getCredential(activity, request)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            Log.w(TAG, "Google sign-in failed", e)
            throw IllegalStateException(googleSignInFailureMessage(e.message))
        }
        val credential = result.credential
        if (credential.type != GoogleIdTokenCredential.TYPE_GOOGLE_ID_TOKEN_CREDENTIAL) {
            throw IllegalStateException("Google didn't return a sign-in token.")
        }
        val google = try {
            GoogleIdTokenCredential.createFrom(credential.data)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            Log.w(TAG, "Google sign-in token could not be read", e)
            throw IllegalStateException("Google didn't return a sign-in token.")
        }
        if (google.idToken.isBlank()) {
            throw IllegalStateException("Google didn't return a sign-in token.")
        }
        return google.idToken
    }

    private const val TAG = "vtodo"
}

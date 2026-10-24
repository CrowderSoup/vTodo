package com.crowdersoup.vtodo.data

import android.app.Activity
import androidx.credentials.CredentialManager
import androidx.credentials.GetCredentialRequest
import androidx.credentials.exceptions.GetCredentialCancellationException
import androidx.credentials.exceptions.NoCredentialException
import com.google.android.libraries.identity.googleid.GetSignInWithGoogleOption
import com.google.android.libraries.identity.googleid.GoogleIdTokenCredential
import kotlin.coroutines.cancellation.CancellationException

/** The person closed the Google account picker. The sign-in screen stays quiet. */
class SignInCancelled : Exception("Sign-in was cancelled.")

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
        } catch (_: GetCredentialCancellationException) {
            throw SignInCancelled()
        } catch (_: NoCredentialException) {
            throw IllegalStateException("No Google account is available on this phone.")
        } catch (e: Exception) {
            val detail = e.message?.takeIf { it.isNotBlank() }
            throw IllegalStateException(detail ?: "Google sign-in didn't finish. Try again.")
        }
        val credential = result.credential
        if (credential.type != GoogleIdTokenCredential.TYPE_GOOGLE_ID_TOKEN_CREDENTIAL) {
            throw IllegalStateException("Google didn't return a sign-in token.")
        }
        val google = try {
            GoogleIdTokenCredential.createFrom(credential.data)
        } catch (e: CancellationException) {
            throw e
        } catch (_: Exception) {
            throw IllegalStateException("Google didn't return a sign-in token.")
        }
        if (google.idToken.isBlank()) {
            throw IllegalStateException("Google didn't return a sign-in token.")
        }
        return google.idToken
    }
}

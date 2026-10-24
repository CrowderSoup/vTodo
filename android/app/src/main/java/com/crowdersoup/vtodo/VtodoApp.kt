package com.crowdersoup.vtodo

import android.app.Application
import androidx.room.Room
import com.crowdersoup.vtodo.data.SessionStore
import com.crowdersoup.vtodo.data.VtodoApi
import com.crowdersoup.vtodo.data.VtodoDatabase
import com.crowdersoup.vtodo.data.VtodoRepository
import com.crowdersoup.vtodo.widget.refreshTodayWidget
import com.crowdersoup.vtodo.work.SyncScheduler
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch

class AppGraph(context: Application) {
    val sessionStore = SessionStore(context)
    val database: VtodoDatabase = Room.databaseBuilder(
        context,
        VtodoDatabase::class.java,
        "vtodo.db",
    ).build()
    val repository = VtodoRepository(database, VtodoApi(), sessionStore)
}

class VtodoApp : Application() {
    lateinit var graph: AppGraph
        private set

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    override fun onCreate() {
        super.onCreate()
        graph = AppGraph(this)
        if (graph.sessionStore.current() != null) {
            SyncScheduler.onSignedIn(this)
            scope.launch { refreshTodayWidget(this@VtodoApp) }
        }
    }
}

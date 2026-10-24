package com.crowdersoup.vtodo

import android.app.Application
import androidx.room.Room
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase
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

private val MIGRATION_1_2 = object : Migration(1, 2) {
    override fun migrate(db: SupportSQLiteDatabase) {
        db.execSQL("ALTER TABLE tasks ADD COLUMN notes TEXT NOT NULL DEFAULT ''")
        db.execSQL("ALTER TABLE statuses ADD COLUMN name TEXT NOT NULL DEFAULT ''")
    }
}

private val MIGRATION_2_3 = object : Migration(2, 3) {
    override fun migrate(db: SupportSQLiteDatabase) {
        db.execSQL("ALTER TABLE tasks ADD COLUMN tags TEXT NOT NULL DEFAULT '[]'")
        db.execSQL("ALTER TABLE statuses ADD COLUMN color TEXT NOT NULL DEFAULT ''")
    }
}

private val MIGRATION_3_4 = object : Migration(3, 4) {
    override fun migrate(db: SupportSQLiteDatabase) {
        db.execSQL("ALTER TABLE tasks ADD COLUMN recurrenceDays INTEGER")
        db.execSQL("ALTER TABLE tasks ADD COLUMN recurrenceFrom TEXT")
    }
}

class AppGraph(context: Application) {
    val sessionStore = SessionStore(context)
    val database: VtodoDatabase = Room.databaseBuilder(
        context,
        VtodoDatabase::class.java,
        "vtodo.db",
    ).addMigrations(MIGRATION_1_2, MIGRATION_2_3, MIGRATION_3_4).build()
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

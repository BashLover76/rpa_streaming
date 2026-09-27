plugins {
    id("com.android.application")
}

android {
    namespace = "fr.local.streamingdb"
    compileSdk = 35

    defaultConfig {
        applicationId = "fr.local.streamingdb"
        minSdk = 26
        targetSdk = 35
        versionCode = 7
        versionName = "0.4.3"
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

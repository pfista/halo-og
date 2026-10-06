/* Atomic complete-pack activation for the Java Android downloader. Refuse an
 * existing destination and fail closed when the filesystem lacks renameat2. */
#include <fcntl.h>
#include <stddef.h>
#include <sys/syscall.h>
#include <unistd.h>

int halo_android_timer_audio_publish(const char *source, const char *destination)
{
#if defined(SYS_renameat2)
	return syscall(SYS_renameat2, AT_FDCWD, source, AT_FDCWD, destination, 1 /* RENAME_NOREPLACE */) == 0;
#else
	(void)source;
	(void)destination;
	return 0;
#endif
}

#ifndef HALO_TIMER_AUDIO_HOST_TEST
#include <jni.h>
JNIEXPORT jboolean JNICALL Java_com_halo_decomp_TimerAudio_publishNoReplace(
	JNIEnv *environment, jclass type, jstring source, jstring destination)
{
	const char *from, *to;
	int result;
	(void)type;
	if (!source || !destination)
		return JNI_FALSE;
	from = (*environment)->GetStringUTFChars(environment, source, NULL);
	if (!from)
		return JNI_FALSE;
	to = (*environment)->GetStringUTFChars(environment, destination, NULL);
	result = to ? halo_android_timer_audio_publish(from, to) : 0;
	if (to)
		(*environment)->ReleaseStringUTFChars(environment, destination, to);
	(*environment)->ReleaseStringUTFChars(environment, source, from);
	return result ? JNI_TRUE : JNI_FALSE;
}
#endif

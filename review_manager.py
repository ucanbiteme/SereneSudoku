"""
Google Play In-App Review Library wrapper for Kivy/Android apps.

Provides a Python interface to the native ReviewManager API via jnius.

Package path notes
------------------
play:review 2.0.x  → com.google.android.play.review.*
play:core   1.10.x → com.google.android.play.core.review.*

Both are tried at init time so this file works regardless of which
gradle dependency version is declared in buildozer.spec.
"""

import time


class ReviewManager:
    """Wrapper for Google Play In-App Review Library."""

    def __init__(self):
        self.review_manager = None  # Java ReviewManager object
        self._pkg = None            # Resolved package prefix
        self._review_info = None    # ReviewInfo cached after requestReviewFlow
        self._initialize()

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def _initialize(self):
        try:
            from kivy.utils import platform
            if platform != 'android':
                print("[REVIEW] Not on Android – stub mode active")
                return

            from jnius import autoclass
            PythonActivity = autoclass('org.kivy.android.PythonActivity')
            activity = PythonActivity.mActivity

            # Try the new separated library path first (review:2.0.x), then
            # the legacy play:core path (core:1.10.x).  Whichever resolves
            # wins.  This avoids ClassNotFoundException when the gradle dep
            # is the new artifact.
            for pkg in (
                'com.google.android.play.review',
                'com.google.android.play.core.review',
            ):
                try:
                    Factory = autoclass(f'{pkg}.ReviewManagerFactory')
                    self.review_manager = Factory.create(activity)
                    self._pkg = pkg
                    print(f"[REVIEW] Initialized via {pkg}.ReviewManagerFactory")
                    return
                except Exception as exc:
                    print(f"[REVIEW] Could not load {pkg}.ReviewManagerFactory: {exc}")

            print("[REVIEW] No compatible ReviewManagerFactory found – check gradle_dependencies")

        except Exception as exc:
            print(f"[REVIEW] Init failed: {exc}")
            self.review_manager = None

    # ------------------------------------------------------------------
    # Step 1 – request the review flow (no UI thread needed)
    # ------------------------------------------------------------------

    def request_review_flow(self, on_success=None, on_error=None):
        """Ask Play Store whether this user/device is eligible to rate.

        Calls on_success() when a ReviewInfo token is ready, or
        on_error(exc) if the request fails.  Both are called on the
        Kivy thread via Clock.
        """
        if not self.review_manager:
            print("[REVIEW] ReviewManager not available")
            if on_error:
                on_error(Exception("ReviewManager not initialized"))
            return

        try:
            # requestReviewFlow() is safe to call from any thread; it
            # starts an async Play Store request and returns a Task.
            request_task = self.review_manager.requestReviewFlow()
            print("[REVIEW] requestReviewFlow() called – polling for completion…")

            from kivy.clock import Clock
            Clock.schedule_once(
                lambda dt: self._poll_request(request_task, on_success, on_error, 0),
                0.5,
            )
        except Exception as exc:
            print(f"[REVIEW] requestReviewFlow() threw: {exc}")
            if on_error:
                on_error(exc)

    def _poll_request(self, task, on_success, on_error, attempt):
        MAX_ATTEMPTS = 30  # 15 s total
        try:
            if not task.isComplete():
                if attempt < MAX_ATTEMPTS:
                    from kivy.clock import Clock
                    Clock.schedule_once(
                        lambda dt: self._poll_request(task, on_success, on_error, attempt + 1),
                        0.5,
                    )
                else:
                    print("[REVIEW] requestReviewFlow timed out after 15 s")
                    if on_error:
                        on_error(Exception("requestReviewFlow timed out"))
                return

            if task.isSuccessful():
                # Cache the ReviewInfo so launch_review_flow can use it
                raw = task.getResult()
                try:
                    from jnius import autoclass, cast
                    ReviewInfo = autoclass(f'{self._pkg}.ReviewInfo')
                    self._review_info = cast(ReviewInfo, raw)
                except Exception:
                    # cast may fail on some jnius versions; use raw object
                    self._review_info = raw
                print("[REVIEW] ReviewInfo obtained – review flow is ready")
                if on_success:
                    on_success()
            else:
                exc = task.getException()
                print(f"[REVIEW] requestReviewFlow not successful: {exc}")
                if on_error:
                    on_error(exc or Exception("requestReviewFlow returned failure"))

        except Exception as exc:
            print(f"[REVIEW] Error polling requestReviewFlow: {exc}")
            if on_error:
                on_error(exc)

    # ------------------------------------------------------------------
    # Step 2 – launch the review sheet (must run on Android UI thread)
    # ------------------------------------------------------------------

    def launch_review_flow(self, on_complete=None, on_error=None):
        """Show the native Play review sheet.

        Must be called after request_review_flow succeeds.  Google Play
        decides whether to actually display the sheet (quota / eligibility).
        on_complete() is called when control returns to the app regardless
        of whether the sheet was shown.
        """
        if not self.review_manager or self._review_info is None:
            print("[REVIEW] Cannot launch – ReviewInfo not ready")
            if on_error:
                on_error(Exception("Review flow not ready: call request_review_flow first"))
            return

        try:
            from kivy.utils import platform
            if platform != 'android':
                print("[REVIEW] Not on Android – skipping launchReviewFlow")
                if on_complete:
                    on_complete()
                return

            from android.runnable import run_on_ui_thread
            from jnius import autoclass

            activity = autoclass('org.kivy.android.PythonActivity').mActivity
            review_info = self._review_info
            mgr = self.review_manager
            launch_state = {'task': None, 'error': None}

            @run_on_ui_thread
            def _do_launch():
                try:
                    launch_state['task'] = mgr.launchReviewFlow(activity, review_info)
                    print("[REVIEW] launchReviewFlow() dispatched on UI thread")
                except Exception as exc:
                    launch_state['error'] = exc
                    print(f"[REVIEW] launchReviewFlow() UI-thread error: {exc}")

            _do_launch()

            from kivy.clock import Clock
            Clock.schedule_once(
                lambda dt: self._poll_launch(launch_state, on_complete, on_error, 0),
                0.5,
            )

        except Exception as exc:
            print(f"[REVIEW] launch_review_flow error: {exc}")
            if on_error:
                on_error(exc)

    def _poll_launch(self, launch_state, on_complete, on_error, attempt):
        MAX_ATTEMPTS = 60  # 30 s total

        # Propagate errors from the UI thread
        if launch_state['error'] is not None:
            print(f"[REVIEW] launchReviewFlow failed: {launch_state['error']}")
            if on_error:
                on_error(launch_state['error'])
            return

        # Still waiting for the UI thread to dispatch _do_launch
        if launch_state['task'] is None:
            if attempt < MAX_ATTEMPTS:
                from kivy.clock import Clock
                Clock.schedule_once(
                    lambda dt: self._poll_launch(launch_state, on_complete, on_error, attempt + 1),
                    0.5,
                )
            else:
                # UI thread never returned the task – treat as completed
                print("[REVIEW] launchReviewFlow task never returned; treating as complete")
                if on_complete:
                    on_complete()
            return

        try:
            task = launch_state['task']
            if task.isComplete():
                print("[REVIEW] launchReviewFlow task complete – control returned to app")
                if on_complete:
                    on_complete()
            else:
                if attempt < MAX_ATTEMPTS:
                    from kivy.clock import Clock
                    Clock.schedule_once(
                        lambda dt: self._poll_launch(launch_state, on_complete, on_error, attempt + 1),
                        0.5,
                    )
                else:
                    print("[REVIEW] launchReviewFlow timed out; treating as complete")
                    if on_complete:
                        on_complete()
        except Exception as exc:
            # isComplete() threw – treat as completed so the app doesn't hang
            print(f"[REVIEW] Error polling launchReviewFlow: {exc}")
            if on_complete:
                on_complete()


def show_review_prompt_if_eligible(app_instance):
    """Convenience function to show review prompt with all safety checks.
    
    Checks if user is eligible (time delays, completion thresholds) 
    then shows the positive-gate dialog.
    
    Args:
        app_instance: The Kivy App instance with game_stats and achievements
    """
    import time

    def _debug(message):
        if hasattr(app_instance, '_show_review_debug_popup'):
            app_instance._show_review_debug_popup(message)
    
    try:
        if not app_instance:
            print("[REVIEW] No app_instance provided")
            return
        
        stats = getattr(app_instance, 'game_stats', None)
        if not stats:
            print("[REVIEW] No game_stats found on app instance")
            _debug("Review check ran, but no game_stats were found on the app instance.")
            return
        
        # Only show after completing at least 3 puzzles
        puzzles_completed = stats.get('puzzles_completed', 0)
        print(f"[REVIEW] Checking eligibility: puzzles_completed={puzzles_completed}")
        if puzzles_completed < 3:
            print(f"[REVIEW] Not enough puzzles completed yet ({puzzles_completed} < 3), skipping prompt")
            _debug(
                f"Review check ran.\n\n"
                f"Blocked reason: puzzles_completed={puzzles_completed} < 3"
            )
            return
        
        # Load review tracking data
        last_shown = stats.get('last_review_prompt_shown', 0)
        shown_count = stats.get('review_prompt_shown_count', 0)
        print(f"[REVIEW] last_shown={last_shown}, shown_count={shown_count}")
        
        # Don't show more than 4 times (over 2 weeks)
        if shown_count >= 4:
            print(f"[REVIEW] Already shown {shown_count} times, skipping prompt")
            _debug(
                f"Review check ran.\n\n"
                f"Blocked reason: review_prompt_shown_count={shown_count} >= 4"
            )
            return
        
        # Wait at least 7 days between prompts
        current_time = time.time()
        days_since_last = (current_time - last_shown) / (24 * 3600) if last_shown else float('inf')
        
        if days_since_last < 7:
            print(f"[REVIEW] Only {days_since_last:.1f} days since last prompt, need 7 days")
            _debug(
                f"Review check ran.\n\n"
                f"Blocked reason: only {days_since_last:.1f} days since last prompt.\n"
                f"puzzles_completed={puzzles_completed}\n"
                f"shown_count={shown_count}"
            )
            return
        
        print("[REVIEW] User is eligible for review prompt! Showing dialog...")
        _debug(
            f"Review check ran.\n\n"
            f"Eligible to show custom review popup.\n"
            f"puzzles_completed={puzzles_completed}\n"
            f"shown_count={shown_count}\n"
            f"days_since_last={days_since_last:.1f}"
        )
        # Clear the pending flag so we don't re-trigger
        app_instance._review_check_pending = False
        app_instance._show_enjoyment_dialog()
        print("[REVIEW] _show_enjoyment_dialog() returned successfully")
    except Exception as e:
        import traceback
        print(f"[REVIEW] ERROR in show_review_prompt_if_eligible: {e}")
        _debug(f"Review check crashed with error:\n\n{e}")
        traceback.print_exc()


def is_android():
    """Check if running on Android."""
    from kivy.utils import platform
    return platform == 'android'

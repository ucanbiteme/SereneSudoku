"""
Windows Store Billing Integration for Serene Sudoku

Handles in-app purchases using Windows.ApplicationModel.Store API via winrt.
Provides same interface as Google Play BillingManager for cross-platform compatibility.
"""

import asyncio
from kivy.utils import platform
from kivy.clock import Clock

# Product IDs (must match Partner Center exactly)
PRODUCT_PREMIUM = "premium_unlock"
PRODUCT_HINTS_10 = "hint_pack_10"
PRODUCT_HINTS_50 = "hint_pack_50"
PRODUCT_HINTS_100 = "hint_pack_100"
PRODUCT_AUTO_SOLVE_5 = "auto_solve_5"
PRODUCT_AUTO_SOLVE_24H = "auto_solve_24h"
PRODUCT_AUTO_SOLVE_FOREVER = "auto_solve_forever"

ALL_PRODUCT_IDS = [
    PRODUCT_PREMIUM,
    PRODUCT_HINTS_10,
    PRODUCT_HINTS_50,
    PRODUCT_HINTS_100,
    PRODUCT_AUTO_SOLVE_5,
    PRODUCT_AUTO_SOLVE_24H,
    PRODUCT_AUTO_SOLVE_FOREVER,
]

NON_CONSUMABLE_PRODUCTS = [
    PRODUCT_PREMIUM,
    PRODUCT_AUTO_SOLVE_FOREVER,
]

CONSUMABLE_PRODUCTS = [
    PRODUCT_HINTS_10,
    PRODUCT_HINTS_50,
    PRODUCT_HINTS_100,
    PRODUCT_AUTO_SOLVE_5,
    PRODUCT_AUTO_SOLVE_24H,
]

PRODUCT_NAME_TO_ID = {
    "Premium Unlock": PRODUCT_PREMIUM,
    "10 Hints": PRODUCT_HINTS_10,
    "50 Hints": PRODUCT_HINTS_50,
    "100 Hints": PRODUCT_HINTS_100,
    "5 Auto-Solves": PRODUCT_AUTO_SOLVE_5,
    "24h Unlimited": PRODUCT_AUTO_SOLVE_24H,
    "Forever Unlimited": PRODUCT_AUTO_SOLVE_FOREVER,
}


class WindowsBillingManager:
    """
    Manages Windows Store IAP using WinRT APIs.
    Provides same interface as Google Play BillingManager.
    """
    
    def __init__(self, app):
        """
        Initialize Windows Store billing manager.
        
        Args:
            app: The main SudokuApp instance for callbacks
        """
        self.app = app
        self.is_connected = False
        self.available = False
        self.store_context = None
        self.product_licenses = {}
        self._restore_callback = None
        
        print("[BILLING-WIN] __init__: WindowsBillingManager instance created")
        self._init_winrt()
    
    def _init_winrt(self):
        """Initialize WinRT API access."""
        if platform != 'win':
            print("[BILLING-WIN] Not on Windows, disabling Windows Store billing")
            return
        
        try:
            import winrt
            from winrt.windows.applicationmodel import store
            from winrt.windows.system import user
            
            self.store_module = store
            self.user_module = user
            self.available = True
            print("[BILLING-WIN] WinRT initialized successfully")
            
        except ImportError as e:
            print(f"[BILLING-WIN] WinRT not available locally: {e}")
            print("[BILLING-WIN] This is NORMAL for local testing. WinRT will only work in packaged Store apps.")
            print("[BILLING-WIN] For local testing, using mock mode.")
            self.available = False
            self._init_mock_mode()

            # If winrt isn't available, look for a bundled native helper (StoreBridge)
            import os
            self.bridge_available = False
            self.bridge_path = None
            candidates = [
                os.path.join(os.getcwd(), '_internal', 'StoreBridge', 'StoreBridge.exe'),
                os.path.join(os.path.dirname(__file__), '_internal', 'StoreBridge', 'StoreBridge.exe'),
                os.path.join(os.getcwd(), 'Tools', 'StoreBridge', 'bin', 'Release', 'net6.0-windows10.0.19041.0', 'StoreBridge.exe'),
                os.path.join(os.getcwd(), 'Tools', 'StoreBridge', 'bin', 'Release', 'net6.0-windows10.0.19041.0', 'win-x64', 'StoreBridge.exe'),
            ]
            for p in candidates:
                try:
                    if os.path.exists(p):
                        self.bridge_available = True
                        self.bridge_path = p
                        print(f"[BILLING-WIN] Found StoreBridge helper at: {p}")
                        # treat as connected so we can use it
                        self.is_connected = True
                        break
                except Exception:
                    continue
    
    def _init_mock_mode(self):
        """Initialize mock/test mode for local development."""
        import os
        # Controlled mock mode: only enable simulated purchases when DEV_BILLING_MOCK=1
        use_mock = os.environ.get('DEV_BILLING_MOCK', '0') == '1'
        if use_mock:
            print("[BILLING-WIN] ✓ Mock mode enabled (DEV_BILLING_MOCK=1)")
            self.is_connected = True  # Pretend we're connected for local testing
        else:
            print("[BILLING-WIN] Mock mode disabled (no DEV_BILLING_MOCK); store APIs will be used when available")
            self.is_connected = False
        self.available = False  # mark unavailable so we don't try real API calls in this environment
    
    def initialize(self):
        """Initialize connection to Windows Store."""
        if not self.available and not getattr(self, 'bridge_available', False):
            print("[BILLING-WIN] Windows Store billing not available")
            return
        
        try:
            # Get StoreContext for current user
            self.store_context = self.store_module.StoreContext.get_default()
            self.is_connected = True
            print("[BILLING-WIN] Connected to Windows Store")
            
            # Load licenses for all products
            asyncio.create_task(self._load_licenses())
            
        except Exception as e:
            print(f"[BILLING-WIN] ERROR initializing: {e}")
            self.is_connected = False

        # If we have a StoreBridge helper, treat as connected and load licenses via bridge
        if getattr(self, 'bridge_available', False) and not self.available:
            print("[BILLING-WIN] Using StoreBridge helper for store operations")
            self.is_connected = True
            # attempt to load licenses via bridge
            try:
                asyncio.create_task(self._load_licenses_via_bridge())
            except Exception as e:
                print(f"[BILLING-WIN] ERROR scheduling bridge license load: {e}")

    async def _load_licenses_via_bridge(self):
        """Load licenses using the native StoreBridge helper."""
        try:
            res = self._call_storebridge({'cmd': 'get_licenses'})
            if res and isinstance(res, dict) and res.get('success'):
                # nothing more to do; real license parsing happens when restore is called
                print("[BILLING-WIN] Bridge reported licenses available")
        except Exception as e:
            print(f"[BILLING-WIN] ERROR loading licenses via bridge: {e}")

    def _call_storebridge(self, payload, timeout=30):
        """Call the StoreBridge helper executable with JSON payload and return parsed JSON result."""
        import subprocess, json, os
        if not getattr(self, 'bridge_available', False) or not self.bridge_path:
            return None
        try:
            proc = subprocess.Popen([self.bridge_path], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            inp = json.dumps(payload)
            out, err = proc.communicate(inp + "\n", timeout=timeout)
            if err:
                # bridge may write non-json logs to stderr; print for diagnostics
                print(f"[BILLING-WIN] StoreBridge stderr: {err.strip()}")
            out = out.strip()
            if not out:
                return None
            try:
                return json.loads(out)
            except Exception:
                # not JSON - return raw
                return out
        except Exception as e:
            print(f"[BILLING-WIN] ERROR calling StoreBridge: {e}")
            return None
    
    async def _load_licenses(self):
        """Load product licenses from Store."""
        if not self.store_context:
            return
        
        try:
            app_license = await self.store_context.get_app_license_async()
            if app_license and app_license.add_on_licenses:
                for addon in app_license.add_on_licenses:
                    license_info = app_license.add_on_licenses[addon]
                    self.product_licenses[addon] = license_info
                    print(f"[BILLING-WIN] Loaded license for: {addon}")
            
        except Exception as e:
            print(f"[BILLING-WIN] ERROR loading licenses: {e}")
    
    def purchase(self, product_name, callback=None):
        """
        Initiate a purchase.
        
        Args:
            product_name: Display name like "Premium Unlock"
            callback: Optional callback function (for interface compatibility with Google Play)
        """
        product_id = PRODUCT_NAME_TO_ID.get(product_name, product_name)
        print(f"[BILLING-WIN] Purchase requested: {product_name} -> {product_id}")
        
        if not self.available:
            # If we have a native bridge, use it to perform purchase
            if getattr(self, 'bridge_available', False):
                print(f"[BILLING-WIN] Using StoreBridge to purchase: {product_id}")
                res = self._call_storebridge({'cmd': 'purchase', 'storeId': product_id})
                if res and isinstance(res, dict) and res.get('success'):
                    status = res.get('status', '')
                    if status.upper().startswith('SUCCEEDED') or status.upper().startswith('OK'):
                        self._deliver_product(product_id)
                    else:
                        print(f"[BILLING-WIN] StoreBridge purchase status: {status}")
                        self._on_purchase_error(status)
                else:
                    print(f"[BILLING-WIN] StoreBridge purchase failed: {res}")
                    self._on_purchase_error(-3)
                return

            if self.is_connected:
                # Mock mode: simulate successful purchase for testing
                print(f"[BILLING-WIN] ★ MOCK MODE: Simulating purchase of {product_id}")
                # Deliver immediately (synchronous) to avoid race conditions during testing
                self._deliver_product(product_id)
            else:
                print("[BILLING-WIN] Cannot purchase - not connected")
                self._on_purchase_error(-1)
            return
        
        # Real WinRT mode (only works in packaged Store apps)
        Clock.schedule_once(lambda dt: self._purchase_async_wrapper(product_id, product_name), 0)
    
    def _purchase_async_wrapper(self, product_id, product_name):
        """Wrapper to handle async purchase with asyncio event loop."""
        try:
            asyncio.create_task(self._purchase_async(product_id, product_name))
        except RuntimeError:
            # No event loop, fall back to mock
            print(f"[BILLING-WIN] No event loop, simulating purchase: {product_id}")
            self._deliver_product(product_id)
    
    async def _purchase_async(self, product_id, product_name):
        """Execute purchase asynchronously."""
        try:
            # Request purchase from user
            purchase_result = await self.store_context.request_purchase_async(product_id)
            
            if purchase_result.status == self.store_module.StorePurchaseStatus.SUCCEEDED:
                print(f"[BILLING-WIN] Purchase successful: {product_id}")
                await self._load_licenses()
                self._deliver_product(product_id)
                
            elif purchase_result.status == self.store_module.StorePurchaseStatus.NOT_PURCHASED:
                print(f"[BILLING-WIN] Purchase cancelled by user: {product_id}")
                self._on_purchase_cancelled()
                
            else:
                print(f"[BILLING-WIN] Purchase failed: {purchase_result.status}")
                self._on_purchase_error(purchase_result.status)
                
        except Exception as e:
            print(f"[BILLING-WIN] ERROR during purchase: {e}")
            self._on_purchase_error(-2)
    
    def check_ownership(self, product_id):
        """Check if user owns a non-consumable product."""
        if product_id in self.product_licenses:
            license_info = self.product_licenses[product_id]
            return license_info.is_active
        return False
    
    def restore_purchases(self, callback=None):
        """
        Restore purchased products for this user.
        
        Args:
            callback: Optional callback function to call when restore completes
        """
        print(f"\n[BILLING-WIN] >>> restore_purchases() called <<<")
        print(f"[BILLING-WIN] Available: {self.available}, Connected: {self.is_connected}")
        self._restore_callback = callback
        
        if not self.available:
            # If bridge available, use it
            if getattr(self, 'bridge_available', False):
                Clock.schedule_once(lambda dt: self._restore_via_bridge(), 0)
                return
            # Mock mode: schedule restore on Kivy event loop
            Clock.schedule_once(lambda dt: self._restore_mock(), 0)
        else:
            # Real WinRT mode (only works in packaged Store apps)
            Clock.schedule_once(lambda dt: self._restore_async_wrapper(), 0)

    def _restore_via_bridge(self):
        """Restore purchases using the native StoreBridge helper."""
        try:
            res = self._call_storebridge({'cmd': 'restore'})
            if res and isinstance(res, dict) and res.get('success'):
                restored = res.get('restored', [])
                print(f"[BILLING-WIN] Bridge restore returned: {restored}")
                if self._restore_callback:
                    self._restore_callback(restored)
                self._on_restore_complete()
                return
            else:
                print(f"[BILLING-WIN] Bridge restore failed: {res}")
        except Exception as e:
            print(f"[BILLING-WIN] ERROR during bridge restore: {e}")

        # Fallback to mock
        self._restore_mock()
    
    def _restore_mock(self):
        """Mock restore for local testing."""
        print("[BILLING-WIN] ★ MOCK MODE: Restore complete (no actual products to restore)")
        if self._restore_callback:
            self._restore_callback([])
        self._on_restore_complete()
    
    def _restore_async_wrapper(self):
        """Wrapper to handle async restore with asyncio event loop."""
        try:
            asyncio.create_task(self._restore_async())
        except RuntimeError:
            # No event loop, use mock mode
            print("[BILLING-WIN] No event loop, using mock restore")
            self._restore_mock()
    
    async def _restore_async(self):
        """Restore purchases asynchronously (real WinRT only)."""
        if not self.store_context:
            print("[BILLING-WIN] No store context - restore failed")
            if self._restore_callback:
                self._restore_callback([])
            self._on_restore_error()
            return
        
        try:
            await self._load_licenses()
            print("[BILLING-WIN] Restore complete")
            
            # Call the callback if provided
            if self._restore_callback:
                self._restore_callback([])
            
            self._on_restore_complete()
            
        except Exception as e:
            print(f"[BILLING-WIN] ERROR restoring: {e}")
            if self._restore_callback:
                self._restore_callback([])
            self._on_restore_error()
    
    def _deliver_product(self, product_id):
        """Deliver product to user."""
        import os
        # Prevent accidental local grant in Store builds unless explicitly allowed for dev testing
        if os.environ.get('DEV_BILLING_MOCK', '0') != '1':
            print(f"[BILLING-WIN] Refusing to deliver product locally in production package: {product_id}")
            return

        print(f"[BILLING-WIN] Delivering product (mock): {product_id}")
        
        if product_id == PRODUCT_PREMIUM:
            print("[BILLING-WIN] ✓ PREMIUM detected - setting has_premium = True")
            self.app.has_premium = True
            self.app._save_stats_and_achievements()
            print("[BILLING-WIN] ✓ Premium unlocked and saved!")
        
        # Handle hint packs
        elif product_id == PRODUCT_HINTS_10:
            print("[BILLING-WIN] ✓ Adding 10 hints")
            self.app.global_hints_remaining = getattr(self.app, 'global_hints_remaining', 0) + 10
            self.app._save_global_hints()
            
        elif product_id == PRODUCT_HINTS_50:
            print("[BILLING-WIN] ✓ Adding 50 hints")
            self.app.global_hints_remaining = getattr(self.app, 'global_hints_remaining', 0) + 50
            self.app._save_global_hints()
            
        elif product_id == PRODUCT_HINTS_100:
            print("[BILLING-WIN] ✓ Adding 100 hints")
            self.app.global_hints_remaining = getattr(self.app, 'global_hints_remaining', 0) + 100
            self.app._save_global_hints()
        
        # Handle auto-solve packs
        elif product_id == PRODUCT_AUTO_SOLVE_5:
            print("[BILLING-WIN] ✓ Adding 5 auto-solves")
            self.app.auto_solve_credits = getattr(self.app, 'auto_solve_credits', 0) + 5
            
        elif product_id == PRODUCT_AUTO_SOLVE_24H:
            print("[BILLING-WIN] ✓ Activating 24h unlimited auto-solves")
            import datetime
            self.app.unlimited_until = (datetime.datetime.now() + datetime.timedelta(hours=24)).isoformat()
            
        elif product_id == PRODUCT_AUTO_SOLVE_FOREVER:
            print("[BILLING-WIN] ✓ Activating permanent unlimited auto-solves")
            self.app.unlimited_forever = True
        
        # Call the standard callback if it exists
        if hasattr(self.app, '_on_purchase_successful'):
            self.app._on_purchase_successful(product_id)

    
    def _on_purchase_cancelled(self):
        """Handle purchase cancellation."""
        if hasattr(self.app, '_on_purchase_cancelled'):
            self.app._on_purchase_cancelled()
    
    def _on_purchase_error(self, error_code):
        """Handle purchase error."""
        print(f"[BILLING-WIN] Purchase error: {error_code}")
        if hasattr(self.app, '_on_purchase_error'):
            self.app._on_purchase_error(error_code)
    
    def _on_restore_complete(self):
        """Handle restore completion."""
        if hasattr(self.app, '_on_restore_complete'):
            self.app._on_restore_complete()
    
    def _on_restore_error(self):
        """Handle restore error."""
        if hasattr(self.app, '_on_restore_error'):
            self.app._on_restore_error()

"""
Cross-Platform Billing Integration for Serene Sudoku

This module handles in-app purchases on both Android (Google Play) and Windows (Store).
- Android: Uses Google Play Billing Library via pyjnius
- Windows: Uses Windows.ApplicationModel.Store via winrt

Product IDs (MUST match exactly in respective stores):
==========================================================
| Product ID            | Type           | Price  |
|-----------------------|----------------|--------|
| premium_unlock        | Non-consumable | $4.99  |
| hint_pack_10          | Consumable     | $0.99  |
| hint_pack_50          | Consumable     | $1.99  |
| hint_pack_100         | Consumable     | $2.99  |
| auto_solve_5          | Consumable     | $0.99  |
| auto_solve_24h        | Consumable     | $1.49  |
| auto_solve_forever    | Non-consumable | $3.99  |
==========================================================
"""

import os
from kivy.utils import platform

# Product ID constants - MUST match Google Play Console exactly
PRODUCT_PREMIUM = "premium_unlock"
PRODUCT_HINTS_10 = "hint_pack_10"
PRODUCT_HINTS_50 = "hint_pack_50"
PRODUCT_HINTS_100 = "hint_pack_100"
PRODUCT_AUTO_SOLVE_5 = "auto_solve_5"
PRODUCT_AUTO_SOLVE_24H = "auto_solve_24h"
PRODUCT_AUTO_SOLVE_FOREVER = "auto_solve_forever"

# All product IDs for querying
ALL_PRODUCT_IDS = [
    PRODUCT_PREMIUM,
    PRODUCT_HINTS_10,
    PRODUCT_HINTS_50,
    PRODUCT_HINTS_100,
    PRODUCT_AUTO_SOLVE_5,
    PRODUCT_AUTO_SOLVE_24H,
    PRODUCT_AUTO_SOLVE_FOREVER,
]

# Non-consumable products (can be restored)
NON_CONSUMABLE_PRODUCTS = [
    PRODUCT_PREMIUM,
    PRODUCT_AUTO_SOLVE_FOREVER,
]

# Consumable products (cannot be restored, consumed after purchase)
CONSUMABLE_PRODUCTS = [
    PRODUCT_HINTS_10,
    PRODUCT_HINTS_50,
    PRODUCT_HINTS_100,
    PRODUCT_AUTO_SOLVE_5,
    PRODUCT_AUTO_SOLVE_24H,
]

# Map display names to product IDs
PRODUCT_NAME_TO_ID = {
    "Premium Unlock": PRODUCT_PREMIUM,
    "10 Hints": PRODUCT_HINTS_10,
    "50 Hints": PRODUCT_HINTS_50,
    "100 Hints": PRODUCT_HINTS_100,
    "5 Auto-Solves": PRODUCT_AUTO_SOLVE_5,
    "24h Unlimited": PRODUCT_AUTO_SOLVE_24H,
    "Forever Unlimited": PRODUCT_AUTO_SOLVE_FOREVER,
}

# Default prices (used when Google Play prices unavailable)
DEFAULT_PRICES = {
    PRODUCT_PREMIUM: "$4.99",
    PRODUCT_HINTS_10: "$0.99",
    PRODUCT_HINTS_50: "$1.99",
    PRODUCT_HINTS_100: "$2.99",
    PRODUCT_AUTO_SOLVE_5: "$0.99",
    PRODUCT_AUTO_SOLVE_24H: "$1.49",
    PRODUCT_AUTO_SOLVE_FOREVER: "$3.99",
}


class BillingManager:
    """
    Manages Google Play Billing operations.
    
    Usage:
        billing = BillingManager(app_instance)
        billing.initialize()
        billing.purchase("Premium Unlock")
        billing.restore_purchases()
    """
    
    def __init__(self, app):
        """
        Initialize the billing manager.
        
        Args:
            app: The main SudokuApp instance for callbacks
        """
        self.app = app
        self.billing_client = None
        self.is_connected = False
        self.product_details = {}  # Cache of product details from Google Play
        self.pending_purchase = None  # Track pending purchase for handling
        self._query_retry_count = 0  # Track query retries
        self._pending_retry_purchase = None  # Product awaiting retry after re-query
        self._in_restore_mode = False  # Flag to suppress popups during restore
        
        # Check if we're on Android
        self.is_android = platform == 'android'
        
        # Java class references (populated on Android)
        self.java_classes_loaded = False
        
    def initialize(self):
        """
        Initialize the billing client and connect to Google Play.
        Call this when the app starts.
        """
        if not self.is_android:
            print("[BILLING] Not on Android, running in test mode")
            self.is_connected = True
            return
        
        if not self._load_java_classes():
            print("[BILLING] Failed to load Java classes")
            return
            
        try:
            # Create listeners
            self._create_listeners()
            
            # Build the billing client
            context = self.PythonActivity.mActivity
            
            self.billing_client = self.BillingClient.newBuilder(context) \
                .setListener(self.purchases_listener) \
                .enablePendingPurchases() \
                .build()
            
            # Start connection
            self.billing_client.startConnection(self.state_listener)
            print("[BILLING] Starting billing client connection...")
            
        except Exception as e:
            print(f"[BILLING] ERROR initializing billing: {e}")
            import traceback
            traceback.print_exc()
    
    def _load_java_classes(self):
        """Load Java classes needed for billing"""
        if self.java_classes_loaded:
            return True
            
        try:
            from jnius import autoclass
            
            # Core Android classes
            self.PythonActivity = autoclass('org.kivy.android.PythonActivity')
            
            # Billing Library classes
            self.BillingClient = autoclass('com.android.billingclient.api.BillingClient')
            self.BillingFlowParams = autoclass('com.android.billingclient.api.BillingFlowParams')
            self.ProductDetailsParams = autoclass('com.android.billingclient.api.BillingFlowParams$ProductDetailsParams')
            self.QueryProductDetailsParams = autoclass('com.android.billingclient.api.QueryProductDetailsParams')
            self.QueryProductDetailsParamsProduct = autoclass('com.android.billingclient.api.QueryProductDetailsParams$Product')
            self.QueryPurchasesParams = autoclass('com.android.billingclient.api.QueryPurchasesParams')
            self.ConsumeParams = autoclass('com.android.billingclient.api.ConsumeParams')
            self.AcknowledgePurchaseParams = autoclass('com.android.billingclient.api.AcknowledgePurchaseParams')
            self.BillingResponseCode = autoclass('com.android.billingclient.api.BillingClient$BillingResponseCode')
            self.ProductType = autoclass('com.android.billingclient.api.BillingClient$ProductType')
            self.PurchaseState = autoclass('com.android.billingclient.api.Purchase$PurchaseState')
            
            # Java utility classes
            self.ArrayList = autoclass('java.util.ArrayList')
            
            self.java_classes_loaded = True
            print("[BILLING] Java classes loaded successfully")
            return True
            
        except Exception as e:
            print(f"[BILLING] ERROR loading Java classes: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _create_listeners(self):
        """Create Java listener objects"""
        from jnius import PythonJavaClass, java_method
        
        billing_manager = self
        
        class BillingStateListener(PythonJavaClass):
            __javainterfaces__ = ['com/android/billingclient/api/BillingClientStateListener']
            __javacontext__ = 'app'
            
            @java_method('(Lcom/android/billingclient/api/BillingResult;)V')
            def onBillingSetupFinished(self, billing_result):
                response_code = billing_result.getResponseCode()
                if response_code == billing_manager.BillingResponseCode.OK:
                    print("[BILLING] Billing client connected successfully")
                    billing_manager.is_connected = True
                    billing_manager._query_product_details()
                    # Schedule a second query after 5 seconds to catch any products
                    # that may not have been returned in the first query
                    from kivy.clock import Clock
                    Clock.schedule_once(lambda dt: billing_manager._retry_query_if_incomplete(), 5)
                else:
                    print(f"[BILLING] Billing setup failed with code: {response_code}")
                    billing_manager.is_connected = False
            
            @java_method('()V')
            def onBillingServiceDisconnected(self):
                print("[BILLING] Billing service disconnected")
                billing_manager.is_connected = False
        
        class PurchasesUpdatedListener(PythonJavaClass):
            __javainterfaces__ = ['com/android/billingclient/api/PurchasesUpdatedListener']
            __javacontext__ = 'app'
            
            @java_method('(Lcom/android/billingclient/api/BillingResult;Ljava/util/List;)V')
            def onPurchasesUpdated(self, billing_result, purchases):
                response_code = billing_result.getResponseCode()
                if response_code == billing_manager.BillingResponseCode.OK and purchases:
                    for i in range(purchases.size()):
                        purchase = purchases.get(i)
                        billing_manager._handle_purchase(purchase)
                elif response_code == billing_manager.BillingResponseCode.USER_CANCELED:
                    print("[BILLING] User cancelled purchase")
                    billing_manager._on_purchase_cancelled()
                else:
                    print(f"[BILLING] Purchase failed with code: {response_code}")
                    billing_manager._on_purchase_error(response_code)
        
        self.state_listener = BillingStateListener()
        self.purchases_listener = PurchasesUpdatedListener()
    
    def _query_product_details(self):
        """Query Google Play for product details (prices, descriptions)"""
        if not self.is_connected:
            print("[BILLING] Cannot query products - not connected")
            return
        
        try:
            from jnius import PythonJavaClass, java_method
            
            billing_manager = self
            
            class ProductDetailsListener(PythonJavaClass):
                __javainterfaces__ = ['com/android/billingclient/api/ProductDetailsResponseListener']
                __javacontext__ = 'app'
                
                @java_method('(Lcom/android/billingclient/api/BillingResult;Ljava/util/List;)V')
                def onProductDetailsResponse(self, billing_result, product_details_list):
                    response_code = billing_result.getResponseCode()
                    debug_msg = billing_result.getDebugMessage()
                    print(f"[BILLING] Product query response code: {response_code}, debug: {debug_msg}")
                    if response_code == billing_manager.BillingResponseCode.OK:
                        count = product_details_list.size()
                        print(f"[BILLING] Got {count} product details (expected {len(ALL_PRODUCT_IDS)})")
                        for i in range(count):
                            product = product_details_list.get(i)
                            product_id = product.getProductId()
                            billing_manager.product_details[product_id] = product
                            try:
                                offer = product.getOneTimePurchaseOfferDetails()
                                price = offer.getFormattedPrice() if offer else 'N/A'
                            except:
                                price = 'N/A'
                            print(f"[BILLING] Cached product: {product_id} (price: {price})")
                        # Log which products are MISSING from the response
                        missing = [pid for pid in ALL_PRODUCT_IDS if pid not in billing_manager.product_details]
                        if missing:
                            print(f"[BILLING] WARNING: Missing products after query: {missing}")
                        else:
                            print(f"[BILLING] All {len(ALL_PRODUCT_IDS)} products cached successfully")
                        # If we have a pending retry purchase, execute it now
                        if billing_manager._pending_retry_purchase:
                            retry_id = billing_manager._pending_retry_purchase
                            billing_manager._pending_retry_purchase = None
                            if retry_id in billing_manager.product_details:
                                print(f"[BILLING] Retry purchase now available: {retry_id}")
                                from kivy.clock import Clock
                                Clock.schedule_once(lambda dt, pid=retry_id: billing_manager._execute_purchase_flow(pid), 0.2)
                            else:
                                print(f"[BILLING] Retry failed - product still not available: {retry_id}")
                                billing_manager._on_purchase_error(-2)
                    else:
                        print(f"[BILLING] Product details query failed: {response_code}, msg: {debug_msg}")
            
            # Build product list
            products_list = self.ArrayList()
            for product_id in ALL_PRODUCT_IDS:
                product = self.QueryProductDetailsParamsProduct.newBuilder() \
                    .setProductId(product_id) \
                    .setProductType(self.ProductType.INAPP) \
                    .build()
                products_list.add(product)
                print(f"[BILLING] Added to query list: {product_id}")
            
            params = self.QueryProductDetailsParams.newBuilder() \
                .setProductList(products_list) \
                .build()
            
            self.billing_client.queryProductDetailsAsync(params, ProductDetailsListener())
            print(f"[BILLING] Querying {len(ALL_PRODUCT_IDS)} product details...")
            
        except Exception as e:
            print(f"[BILLING] ERROR querying products: {e}")
            import traceback
            traceback.print_exc()
    
    def _retry_query_if_incomplete(self):
        """Re-query product details if not all products were cached on first attempt"""
        missing = [pid for pid in ALL_PRODUCT_IDS if pid not in self.product_details]
        if missing:
            print(f"[BILLING] Retry query - {len(missing)} products still missing: {missing}")
            self._query_retry_count += 1
            self._query_product_details()
        else:
            print(f"[BILLING] All {len(ALL_PRODUCT_IDS)} products cached, no retry needed")
    
    def _query_single_product(self, product_id):
        """Query Google Play for a single product's details (used for retry on purchase)"""
        if not self.is_connected:
            print(f"[BILLING] Cannot query single product - not connected")
            return
        
        try:
            from jnius import PythonJavaClass, java_method
            
            billing_manager = self
            
            class SingleProductListener(PythonJavaClass):
                __javainterfaces__ = ['com/android/billingclient/api/ProductDetailsResponseListener']
                __javacontext__ = 'app'
                
                @java_method('(Lcom/android/billingclient/api/BillingResult;Ljava/util/List;)V')
                def onProductDetailsResponse(self, billing_result, product_details_list):
                    response_code = billing_result.getResponseCode()
                    debug_msg = billing_result.getDebugMessage()
                    print(f"[BILLING] Single product query response: code={response_code}, debug={debug_msg}")
                    if response_code == billing_manager.BillingResponseCode.OK:
                        count = product_details_list.size()
                        print(f"[BILLING] Single query returned {count} products")
                        for i in range(count):
                            product = product_details_list.get(i)
                            pid = product.getProductId()
                            billing_manager.product_details[pid] = product
                            print(f"[BILLING] Single query cached: {pid}")
                    else:
                        print(f"[BILLING] Single product query failed: {response_code}")
                    
                    # Execute the pending retry purchase
                    if billing_manager._pending_retry_purchase:
                        retry_id = billing_manager._pending_retry_purchase
                        billing_manager._pending_retry_purchase = None
                        if retry_id in billing_manager.product_details:
                            print(f"[BILLING] Retry: product now available: {retry_id}")
                            from kivy.clock import Clock
                            Clock.schedule_once(lambda dt, pid=retry_id: billing_manager._execute_purchase_flow(pid), 0.2)
                        else:
                            print(f"[BILLING] Retry: product STILL not available: {retry_id}")
                            billing_manager._on_purchase_error(-2)
            
            products_list = self.ArrayList()
            product = self.QueryProductDetailsParamsProduct.newBuilder() \
                .setProductId(product_id) \
                .setProductType(self.ProductType.INAPP) \
                .build()
            products_list.add(product)
            
            params = self.QueryProductDetailsParams.newBuilder() \
                .setProductList(products_list) \
                .build()
            
            self.billing_client.queryProductDetailsAsync(params, SingleProductListener())
            print(f"[BILLING] Querying single product: {product_id}")
            
        except Exception as e:
            print(f"[BILLING] ERROR querying single product {product_id}: {e}")
            import traceback
            traceback.print_exc()
            if self._pending_retry_purchase:
                self._pending_retry_purchase = None
                self._on_purchase_error(-2)
    
    def _execute_purchase_flow(self, product_id):
        """Execute the actual billing flow for a product that is confirmed in cache"""
        try:
            product_details = self.product_details[product_id]
            
            # Build the product details params
            product_details_params = self.ProductDetailsParams.newBuilder() \
                .setProductDetails(product_details) \
                .build()
            
            product_params_list = self.ArrayList()
            product_params_list.add(product_details_params)
            
            # Build the billing flow params
            flow_params = self.BillingFlowParams.newBuilder() \
                .setProductDetailsParamsList(product_params_list) \
                .build()
            
            # Launch the billing flow
            activity = self.PythonActivity.mActivity
            billing_result = self.billing_client.launchBillingFlow(activity, flow_params)
            
            response_code = billing_result.getResponseCode()
            if response_code != self.BillingResponseCode.OK:
                print(f"[BILLING] Launch billing flow failed: {response_code}")
                self._on_purchase_error(response_code)
            else:
                print(f"[BILLING] Billing flow launched for: {product_id}")
                
        except Exception as e:
            print(f"[BILLING] ERROR executing purchase flow: {e}")
            import traceback
            traceback.print_exc()
            self._on_purchase_error(-3)

    def purchase(self, product_name):
        """
        Initiate a purchase flow.
        
        Args:
            product_name: Display name like "Premium Unlock" or "10 Hints"
        """
        # Convert display name to product ID
        product_id = PRODUCT_NAME_TO_ID.get(product_name, product_name)
        
        print(f"[BILLING] Purchase requested: {product_name} -> {product_id}")
        print(f"[BILLING] Current cache has {len(self.product_details)} products: {list(self.product_details.keys())}")
        
        if not self.is_android:
            print(f"[BILLING] Simulating purchase on non-Android: {product_id}")
            self._deliver_product(product_id)
            return
        
        if not self.is_connected:
            print("[BILLING] Cannot purchase - not connected to billing service")
            self._on_purchase_error(-1)
            return
        
        self.pending_purchase = product_id
        
        if product_id in self.product_details:
            # Product is in cache, proceed directly
            self._execute_purchase_flow(product_id)
        else:
            # Product NOT in cache - re-query Google Play for this specific product
            print(f"[BILLING] Product {product_id} not in cache, triggering re-query...")
            self._pending_retry_purchase = product_id
            self._query_single_product(product_id)
    
    def _handle_purchase(self, purchase):
        """Handle a successful purchase"""
        try:
            purchase_state = purchase.getPurchaseState()
            
            if purchase_state == self.PurchaseState.PURCHASED:
                products = purchase.getProducts()
                for i in range(products.size()):
                    product_id = products.get(i)
                    print(f"[BILLING] Processing purchase for: {product_id}")
                    
                    if not purchase.isAcknowledged():
                        if product_id in CONSUMABLE_PRODUCTS:
                            self._consume_purchase(purchase, product_id)
                        else:
                            self._acknowledge_purchase(purchase, product_id)
                    else:
                        # Skip popup during restore - will show single restore popup instead
                        if self._in_restore_mode:
                            self._deliver_product_silent(product_id)
                        else:
                            self._deliver_product(product_id)
                        
            elif purchase_state == self.PurchaseState.PENDING:
                print("[BILLING] Purchase is pending - will be delivered when complete")
                
        except Exception as e:
            print(f"[BILLING] ERROR handling purchase: {e}")
            import traceback
            traceback.print_exc()
    
    def _consume_purchase(self, purchase, product_id):
        """Consume a consumable purchase"""
        try:
            from jnius import PythonJavaClass, java_method
            
            billing_manager = self
            pid = product_id
            
            class ConsumeListener(PythonJavaClass):
                __javainterfaces__ = ['com/android/billingclient/api/ConsumeResponseListener']
                __javacontext__ = 'app'
                
                @java_method('(Lcom/android/billingclient/api/BillingResult;Ljava/lang/String;)V')
                def onConsumeResponse(self, billing_result, purchase_token):
                    response_code = billing_result.getResponseCode()
                    if response_code == billing_manager.BillingResponseCode.OK:
                        print(f"[BILLING] Consumed: {pid}")
                        if billing_manager._in_restore_mode:
                            billing_manager._deliver_product_silent(pid)
                        else:
                            billing_manager._deliver_product(pid)
                    else:
                        print(f"[BILLING] Consume failed: {response_code}")
            
            params = self.ConsumeParams.newBuilder() \
                .setPurchaseToken(purchase.getPurchaseToken()) \
                .build()
            
            self.billing_client.consumeAsync(params, ConsumeListener())
            
        except Exception as e:
            print(f"[BILLING] ERROR consuming: {e}")
    
    def _acknowledge_purchase(self, purchase, product_id):
        """Acknowledge a non-consumable purchase"""
        try:
            from jnius import PythonJavaClass, java_method
            
            billing_manager = self
            pid = product_id
            
            class AcknowledgeListener(PythonJavaClass):
                __javainterfaces__ = ['com/android/billingclient/api/AcknowledgePurchaseResponseListener']
                __javacontext__ = 'app'
                
                @java_method('(Lcom/android/billingclient/api/BillingResult;)V')
                def onAcknowledgePurchaseResponse(self, billing_result):
                    response_code = billing_result.getResponseCode()
                    if response_code == billing_manager.BillingResponseCode.OK:
                        print(f"[BILLING] Acknowledged: {pid}")
                        if billing_manager._in_restore_mode:
                            billing_manager._deliver_product_silent(pid)
                        else:
                            billing_manager._deliver_product(pid)
                    else:
                        print(f"[BILLING] Acknowledge failed: {response_code}")
            
            params = self.AcknowledgePurchaseParams.newBuilder() \
                .setPurchaseToken(purchase.getPurchaseToken()) \
                .build()
            
            self.billing_client.acknowledgePurchase(params, AcknowledgeListener())
            
        except Exception as e:
            print(f"[BILLING] ERROR acknowledging: {e}")
    
    def _deliver_product(self, product_id):
        """Deliver a purchased product to the user"""
        print(f"[BILLING] Delivering product: {product_id}")
        
        try:
            if product_id == PRODUCT_PREMIUM:
                self.app.has_premium = True
                self.app._save_stats_and_achievements()
                try:
                    self.app._update_hint_button_text()
                    self.app._update_auto_solve_button_text()
                except:
                    pass
                print("[BILLING] Premium unlocked!")
                
            elif product_id == PRODUCT_HINTS_10:
                self.app.global_hints_remaining += 10
                self.app._save_global_hints()
                try:
                    self.app._update_hint_button_text()
                except:
                    pass
                print("[BILLING] Added 10 hints")
                
            elif product_id == PRODUCT_HINTS_50:
                self.app.global_hints_remaining += 50
                self.app._save_global_hints()
                try:
                    self.app._update_hint_button_text()
                except:
                    pass
                print("[BILLING] Added 50 hints")
                
            elif product_id == PRODUCT_HINTS_100:
                self.app.global_hints_remaining += 100
                self.app._save_global_hints()
                try:
                    self.app._update_hint_button_text()
                except:
                    pass
                print("[BILLING] Added 100 hints")
                
            elif product_id == PRODUCT_AUTO_SOLVE_5:
                self.app.auto_solve_credits += 5
                try:
                    self.app._update_auto_solve_button_text()
                except:
                    pass
                print("[BILLING] Added 5 auto-solves")
                
            elif product_id == PRODUCT_AUTO_SOLVE_24H:
                import datetime
                self.app.unlimited_until = (datetime.datetime.now() + datetime.timedelta(hours=24)).isoformat()
                try:
                    self.app._update_auto_solve_button_text()
                except:
                    pass
                print(f"[BILLING] 24h unlimited until: {self.app.unlimited_until}")
                
            elif product_id == PRODUCT_AUTO_SOLVE_FOREVER:
                self.app.unlimited_forever = True
                self.app._save_stats_and_achievements()
                try:
                    self.app._update_auto_solve_button_text()
                except:
                    pass
                print("[BILLING] Forever unlimited unlocked!")
            
            self._on_purchase_success(product_id)
            
        except Exception as e:
            print(f"[BILLING] ERROR delivering product: {e}")
            import traceback
            traceback.print_exc()
    
    def _deliver_product_silent(self, product_id):
        """Deliver a product WITHOUT showing success popup (used for restore)"""
        print(f"[BILLING] Silently delivering product: {product_id}")
        
        try:
            if product_id == PRODUCT_PREMIUM:
                self.app.has_premium = True
                self.app._save_stats_and_achievements()
                try:
                    self.app._update_hint_button_text()
                    self.app._update_auto_solve_button_text()
                except:
                    pass
                print("[BILLING] Premium unlocked (silent)!")
                
            elif product_id == PRODUCT_AUTO_SOLVE_FOREVER:
                self.app.unlimited_forever = True
                self.app._save_stats_and_achievements()
                try:
                    self.app._update_auto_solve_button_text()
                except:
                    pass
                print("[BILLING] Forever unlimited unlocked (silent)!")
                
        except Exception as e:
            print(f"[BILLING] ERROR silently delivering product: {e}")
            import traceback
            traceback.print_exc()
    
    def restore_purchases(self, callback=None):
        """
        Restore previously purchased non-consumable products.
        
        Args:
            callback: Optional function(restored_list) called when complete
        """
        print("[BILLING] Restore purchases initiated")
        self._in_restore_mode = True  # Suppress individual popups during restore
        
        if not self.is_android:
            print("[BILLING] Non-Android: checking local storage")
            restored = []
            if getattr(self.app, 'has_premium', False):
                restored.append(PRODUCT_PREMIUM)
            if getattr(self.app, 'unlimited_forever', False):
                restored.append(PRODUCT_AUTO_SOLVE_FOREVER)
            if callback:
                callback(restored)
            self._in_restore_mode = False  # Re-enable popups
            return
        
        if not self.is_connected:
            print("[BILLING] Cannot restore - not connected")
            if callback:
                callback([])
            self._in_restore_mode = False  # Re-enable popups
            return
        
        try:
            from jnius import PythonJavaClass, java_method
            
            billing_manager = self
            restore_callback = callback
            
            class PurchasesListener(PythonJavaClass):
                __javainterfaces__ = ['com/android/billingclient/api/PurchasesResponseListener']
                __javacontext__ = 'app'
                
                @java_method('(Lcom/android/billingclient/api/BillingResult;Ljava/util/List;)V')
                def onQueryPurchasesResponse(self, billing_result, purchases):
                    response_code = billing_result.getResponseCode()
                    restored = []
                    
                    if response_code == billing_manager.BillingResponseCode.OK and purchases:
                        print(f"[BILLING] Found {purchases.size()} owned purchases")
                        for i in range(purchases.size()):
                            purchase = purchases.get(i)
                            products = purchase.getProducts()
                            for j in range(products.size()):
                                product_id = products.get(j)
                                if product_id in NON_CONSUMABLE_PRODUCTS:
                                    print(f"[BILLING] Restoring: {product_id}")
                                    billing_manager._deliver_product_silent(product_id)
                                    restored.append(product_id)
                    else:
                        print(f"[BILLING] Query purchases response: {response_code}")
                    
                    if restore_callback:
                        restore_callback(restored)
                    billing_manager._in_restore_mode = False  # Re-enable popups after restore complete
            
            params = self.QueryPurchasesParams.newBuilder() \
                .setProductType(self.ProductType.INAPP) \
                .build()
            
            self.billing_client.queryPurchasesAsync(params, PurchasesListener())
            print("[BILLING] Querying owned purchases...")
            
        except Exception as e:
            print(f"[BILLING] ERROR restoring: {e}")
            import traceback
            traceback.print_exc()
            if callback:
                callback([])
    
    def _on_purchase_success(self, product_id):
        """Called when a purchase succeeds"""
        print(f"[BILLING] Purchase successful: {product_id}")
        self.pending_purchase = None
        
        # Show success popup on main thread
        from kivy.clock import Clock
        def show_success(dt):
            try:
                if hasattr(self.app, '_show_purchase_success_popup'):
                    self.app._show_purchase_success_popup(product_id)
            except Exception as e:
                print(f"[BILLING] Error showing success popup: {e}")
        Clock.schedule_once(show_success, 0.1)
    
    def _on_purchase_cancelled(self):
        """Called when user cancels a purchase"""
        print("[BILLING] Purchase cancelled by user")
        self.pending_purchase = None
    
    def _on_purchase_error(self, error_code):
        """Called when a purchase fails"""
        print(f"[BILLING] Purchase error: {error_code}")
        self.pending_purchase = None
        
        # Error code 7 = ITEM_ALREADY_OWNED - Google Play shows its own notification,
        # so we don't need to show our own error popup for this case
        if error_code == 7:
            print("[BILLING] Item already owned - suppressing error popup")
            return
        
        from kivy.clock import Clock
        def show_error(dt):
            try:
                if hasattr(self.app, '_show_purchase_error_popup'):
                    self.app._show_purchase_error_popup(error_code)
            except Exception as e:
                print(f"[BILLING] Error showing error popup: {e}")
        Clock.schedule_once(show_error, 0.1)
    
    def get_price(self, product_name):
        """
        Get the localized price for a product.
        
        Args:
            product_name: Display name like "Premium Unlock"
            
        Returns:
            Price string like "$5.99"
        """
        product_id = PRODUCT_NAME_TO_ID.get(product_name, product_name)
        
        if self.is_android and product_id in self.product_details:
            try:
                product = self.product_details[product_id]
                offer = product.getOneTimePurchaseOfferDetails()
                if offer:
                    return offer.getFormattedPrice()
            except:
                pass
        
        return DEFAULT_PRICES.get(product_id, "$?.??")
    
    def cleanup(self):
        """Clean up billing client when app closes"""
        if self.billing_client and self.is_connected:
            try:
                self.billing_client.endConnection()
                print("[BILLING] Billing client disconnected")
            except:
                pass


# ============================================================================
# GOOGLE PLAY CONSOLE SETUP INSTRUCTIONS
# ============================================================================
"""
STEP-BY-STEP: Setting Up In-App Products in Google Play Console

1. LOG IN to Google Play Console: https://play.google.com/console

2. SELECT YOUR APP (or create it first)

3. GO TO: Monetization > Products > In-app products

4. CREATE EACH PRODUCT:

   Click "Create product" and enter:
   
   PRODUCT 1: Premium Unlock
   - Product ID: premium_unlock
   - Name: Premium Unlock
   - Description: Unlock unlimited hints, auto-solves, statistics, and achievements
   - Default price: $4.99
   - Status: Active
   
   PRODUCT 2: 10 Hints Pack
   - Product ID: hint_pack_10
   - Name: 10 Hints
   - Description: Add 10 hints to your hint balance
   - Default price: $0.99
   - Status: Active
   
   PRODUCT 3: 50 Hints Pack
   - Product ID: hint_pack_50
   - Name: 50 Hints
   - Description: Add 50 hints to your hint balance
   - Default price: $1.49
   - Status: Active
   
   PRODUCT 4: 100 Hints Pack
   - Product ID: hint_pack_100
   - Name: 100 Hints
   - Description: Add 100 hints to your hint balance
   - Default price: $2.99
   - Status: Active
   
   PRODUCT 5: 5 Auto-Solves
   - Product ID: auto_solve_5
   - Name: 5 Auto-Solves
   - Description: Add 5 auto-solve credits
   - Default price: $0.99
   - Status: Active
   
   PRODUCT 6: 24-Hour Unlimited Auto-Solves
   - Product ID: auto_solve_24h
   - Name: 24h Unlimited Auto-Solves
   - Description: Unlimited auto-solves for 24 hours
   - Default price: $1.49
   - Status: Active
   
   PRODUCT 7: Forever Unlimited Auto-Solves
   - Product ID: auto_solve_forever
   - Name: Forever Unlimited Auto-Solves
   - Description: Permanent unlimited auto-solves
   - Default price: $4.99
   - Status: Active

5. IMPORTANT: Product IDs must match EXACTLY as shown above!

6. SAVE and ACTIVATE each product

7. TESTING: Add license testers in Settings > License testing
   - Add email addresses of test accounts
   - Testers won't be charged for purchases

8. UPLOAD: You must upload at least one APK/AAB to a testing track 
   before in-app products become available for testing
"""


# ============================================================================
# CROSS-PLATFORM FACTORY
# ============================================================================

def create_billing_manager(app):
    """
    Factory function to create the appropriate billing manager for the platform.
    
    Args:
        app: The main app instance
        
    Returns:
        BillingManager (Android) or WindowsBillingManager (Windows)
    """
    detected_platform = platform
    print(f"\n{'='*60}")
    print(f"[BILLING-FACTORY] Creating billing manager")
    print(f"[BILLING-FACTORY] Detected platform: '{detected_platform}'")
    print(f"{'='*60}\n")
    
    if detected_platform == 'android':
        print("[BILLING-FACTORY] ✓ Creating Android Google Play BillingManager")
        return BillingManager(app)
    elif detected_platform == 'win':
        print("[BILLING-FACTORY] ✓ Creating Windows Store BillingManager")
        from windows_billing import WindowsBillingManager
        mgr = WindowsBillingManager(app)
        print(f"[BILLING-FACTORY] ✓ WindowsBillingManager instance created: {type(mgr)}")
        return mgr
    else:
        print(f"[BILLING-FACTORY] ⚠ Platform '{detected_platform}' not supported, falling back to BillingManager")
        return BillingManager(app)

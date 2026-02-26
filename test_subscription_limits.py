"""
Test script to verify subscription limits and credit tracking.
This script simulates API calls to ensure credit limits are enforced.
"""
import asyncio
from app.services.subscription_service import subscription_service
from app.database import db

async def test_subscription_limits():
    """Test that subscription limits are properly enforced"""
    print("=" * 60)
    print("Testing Subscription Credit Tracking System")
    print("=" * 60)
    
    # Connect to database first
    print("\n0. Connecting to database...")
    await db.connect_to_database()
    
    if db.db is None:
        print("❌ Database connection failed")
        return
    
    # Create a test user subscription
    test_user_id = "test_user_123"
    
    # Clean up any existing test subscription
    await db.db.subscriptions.delete_many({"userId": test_user_id})
    
    # Create a trial subscription with 5 document limit
    print("\n1. Creating test subscription with 5 document limit...")
    sub = await subscription_service.create_trial(test_user_id)
    if sub:
        print(f"   ✓ Subscription created: {sub['documentsUsed']}/{sub['documentsLimit']} used")
    else:
        print("   ❌ Failed to create subscription")
        return
    
    # Test can_process when under limit
    print("\n2. Testing can_process with 0/5 used...")
    can_process, sub, message = await subscription_service.can_process(test_user_id)
    print(f"   ✓ Can process: {can_process}, Message: {message}")
    if not can_process:
        print("   ❌ Should be able to process!")
        return
    
    # Simulate processing documents one by one
    print("\n3. Simulating document processing (incrementing usage)...")
    for i in range(1, 6):
        can_process, sub, message = await subscription_service.can_process(test_user_id)
        if can_process:
            print(f"   Processing document {i}...")
            updated_sub = await subscription_service.increment_usage(test_user_id)
            print(f"   ✓ Document {i} processed. Usage: {updated_sub['documentsUsed']}/{updated_sub['documentsLimit']}")
        else:
            print(f"   ⚠ Cannot process document {i}: {message}")
            break
    
    # Test can_process when limit reached
    print("\n4. Testing can_process when limit is reached (5/5 used)...")
    can_process, sub, message = await subscription_service.can_process(test_user_id)
    print(f"   ✓ Can process: {can_process}, Message: {message}")
    if can_process:
        print("   ❌ Should NOT be able to process - limit reached!")
    else:
        print(f"   ✓ Correctly blocked: {message}")
    
    # Try to increment when at limit
    print("\n5. Attempting to process when at limit...")
    can_process, sub, message = await subscription_service.can_process(test_user_id)
    if not can_process:
        print(f"   ✓ Correctly prevented processing: {message}")
    else:
        print("   ❌ Should be blocked!")
    
    # Clean up
    print("\n6. Cleaning up test data...")
    await db.db.subscriptions.delete_many({"userId": test_user_id})
    print("   ✓ Test data cleaned up")
    
    # Close database connection
    await db.close_database_connection()
    
    print("\n" + "=" * 60)
    print("✅ Subscription Credit Tracking System Test Complete!")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(test_subscription_limits())

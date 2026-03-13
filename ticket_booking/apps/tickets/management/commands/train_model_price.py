import pandas as pd
import joblib
import os
import random
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Avg, Sum
from sklearn.ensemble import RandomForestRegressor

# Import Models
from apps.events.models import Match
from apps.tickets.models import SectionPrice
from apps.orders.models import OrderDetail

class Command(BaseCommand):
    help = 'Huấn luyện AI với logic Cầu cứng (Inelastic Demand) cho trận HOT'

    def handle(self, *args, **kwargs):
        self.stdout.write(self.style.WARNING('1. Đang trích xuất dữ liệu thực tế...'))
        
        data = []
        matches = Match.objects.all()
        
        # 1. LẤY DỮ LIỆU THẬT (REAL DATA)
        for match in matches:
            # Lấy giá trung bình
            avg_price = SectionPrice.objects.filter(match=match).aggregate(Avg('price'))['price__avg']
            if not avg_price: continue

            # Lấy tổng vé bán
            total_sold = OrderDetail.objects.filter(pricing__match=match).count()
            
            # Lấy tổng sức chứa thực tế của trận này (để tính fill_rate nếu cần normalize)
            # Nhưng Random Forest có thể học số tuyệt đối nếu quy mô sân tương đồng
            
            data.append({
                'day_of_week': match.match_time.weekday(),
                'hour': match.match_time.hour,
                'is_hot_match': 1 if match.is_hot_match else 0,
                'importance': match.importance,
                'price': float(avg_price),
                'total_sold': total_sold
            })

        # 2. INJECT DỮ LIỆU GIẢ ĐỊNH PHÂN TẦNG (TIERED INJECTION)
        print("   -> Đang tiêm dữ liệu phân tầng (4 Tiers)...")
        
        import random
        AVG_CAPACITY = 1200 

        # --- TIER 1: SIÊU HOT (Importance 5, Derby) ---
        # Khách hàng: Bất chấp giá.
        for _ in range(200):
            price = random.randint(200000, 2000000)
            if price <= 800000: fill = random.uniform(0.95, 1.0) # Dưới 800k là auto full
            elif price <= 1500000: fill = random.uniform(0.70, 0.90)
            else: fill = random.uniform(0.30, 0.60)
            
            data.append({
                'day_of_week': random.choice([5, 6]), 'hour': random.choice([19, 20]),
                'is_hot_match': 1, 'importance': 5,
                'price': price, 'total_sold': int(AVG_CAPACITY * fill)
            })

        # --- TIER 2: SAO SỐ / CỬA TRÊN (Importance 4 - VD: Man City vs Sheffield) ---
        # Khách hàng: Chịu chi để xem ngôi sao, nhưng không "điên" như trận Derby.
        # Giá 300k vẫn phải bán tốt (80-90%), nhưng lên 600k là giảm.
        for _ in range(200):
            price = random.randint(150000, 1000000)
            if price <= 400000: 
                fill = random.uniform(0.85, 0.98) # <--- ĐIỂM KHÁC BIỆT: Giá 290k-400k vẫn full
            elif price <= 700000: 
                fill = random.uniform(0.50, 0.75)
            else: 
                fill = random.uniform(0.10, 0.30)

            data.append({
                'day_of_week': random.randint(0, 6), 'hour': random.choice([17, 19, 20]),
                'is_hot_match': 0, 'importance': 4, # Importance 4
                'price': price, 'total_sold': int(AVG_CAPACITY * fill)
            })

        # --- TIER 3: TRUNG BÌNH (Importance 3) ---
        # Khách hàng: Cân nhắc giá kỹ.
        for _ in range(200):
            price = random.randint(100000, 600000)
            if price <= 200000: fill = random.uniform(0.70, 0.90)
            elif price <= 350000: fill = random.uniform(0.40, 0.60)
            else: fill = random.uniform(0.05, 0.20)

            data.append({
                'day_of_week': random.randint(0, 6), 'hour': random.randint(17, 20),
                'is_hot_match': 0, 'importance': 3,
                'price': price, 'total_sold': int(AVG_CAPACITY * fill)
            })

        # --- TIER 4: ĐỘI YẾU / Ế (Importance 1, 2 - VD: Burnley vs Luton) ---
        # Khách hàng: Chỉ đi xem nếu rẻ như cho.
        # Giá 290k là CỰC ĐẮT với họ -> Fill rate phải thấp thảm hại.
        for _ in range(200):
            price = random.randint(50000, 400000)
            if price <= 100000: 
                fill = random.uniform(0.60, 0.85) # Rẻ bèo mới mua
            elif price <= 200000: 
                fill = random.uniform(0.20, 0.40) # Hơi đắt tí là nghỉ
            else: 
                fill = 0 # Trên 200k là sân trống
            
            data.append({
                'day_of_week': random.randint(0, 6), 'hour': random.randint(14, 17),
                'is_hot_match': 0, 
                'importance': random.choice([1, 2]), # Importance 1-2
                'price': price, 'total_sold': int(AVG_CAPACITY * fill)
            })

        # 3. TRAIN MODEL
        df = pd.DataFrame(data)
        self.stdout.write(f"   -> Tổng dữ liệu train: {len(df)} mẫu.")

        X = df[['day_of_week', 'hour', 'is_hot_match', 'importance', 'price']]
        y = df['total_sold']

        self.stdout.write(self.style.WARNING('2. Đang huấn luyện...'))
        
        # Tăng n_estimators để model học kỹ hơn
        model = RandomForestRegressor(n_estimators=300, random_state=42)
        model.fit(X, y)

        # Lưu model
        save_path = os.path.join(settings.BASE_DIR, 'ml_models')
        if not os.path.exists(save_path): os.makedirs(save_path)
        joblib.dump(model, os.path.join(save_path, 'price_optimization_model.pkl'))

        self.stdout.write(self.style.SUCCESS('✅ Train xong! '))


# 1
# import pandas as pd
# import joblib
# import os
# import random
# from django.conf import settings
# from django.core.management.base import BaseCommand
# from django.db.models import Avg
# # --- QUAN TRỌNG: Dùng Regressor cho bài toán dự báo số lượng ---
# from sklearn.ensemble import RandomForestRegressor 

# # Import Models
# from apps.events.models import Match
# from apps.tickets.models import SectionPrice
# from apps.orders.models import OrderDetail

# class Command(BaseCommand):
#     help = 'Huấn luyện AI Giá vé (Fixed) & Báo cáo độ tin cậy'

#     def handle(self, *args, **kwargs):
#         self.stdout.write(self.style.WARNING('1. Đang chuẩn bị dữ liệu (Real + 4 Tiers Injection)...'))
        
#         data = []
#         matches = Match.objects.all()
        
#         # --- 1. REAL DATA ---
#         for match in matches:
#             avg_price = SectionPrice.objects.filter(match=match).aggregate(Avg('price'))['price__avg']
#             if not avg_price: continue
#             total_sold = OrderDetail.objects.filter(pricing__match=match).count()
#             data.append({
#                 'day_of_week': match.match_time.weekday(),
#                 'hour': match.match_time.hour,
#                 'is_hot_match': 1 if match.is_hot_match else 0,
#                 'importance': match.importance,
#                 'price': float(avg_price),
#                 'total_sold': total_sold
#             })

#         # --- 2. SYNTHETIC DATA (4 TIERS) ---
#         AVG_CAPACITY = 1200 
#                 # --- TIER 1: SIÊU HOT (Importance 5, Derby) ---
#         # Khách hàng: Bất chấp giá.
#         for _ in range(200):
#             price = random.randint(200000, 2000000)
#             if price <= 800000: fill = random.uniform(0.95, 1.0) # Dưới 800k là auto full
#             elif price <= 1500000: fill = random.uniform(0.70, 0.90)
#             else: fill = random.uniform(0.30, 0.60)
            
#             data.append({
#                 'day_of_week': random.choice([5, 6]), 'hour': random.choice([19, 20]),
#                 'is_hot_match': 1, 'importance': 5,
#                 'price': price, 'total_sold': int(AVG_CAPACITY * fill)
#             })

#         # --- TIER 2: SAO SỐ / CỬA TRÊN (Importance 4 - VD: Man City vs Sheffield) ---
#         # Khách hàng: Chịu chi để xem ngôi sao, nhưng không "điên" như trận Derby.
#         # Giá 300k vẫn phải bán tốt (80-90%), nhưng lên 600k là giảm.
#         for _ in range(200):
#             price = random.randint(150000, 1000000)
#             if price <= 400000: 
#                 fill = random.uniform(0.85, 0.98) # <--- ĐIỂM KHÁC BIỆT: Giá 290k-400k vẫn full
#             elif price <= 700000: 
#                 fill = random.uniform(0.50, 0.75)
#             else: 
#                 fill = random.uniform(0.10, 0.30)

#             data.append({
#                 'day_of_week': random.randint(0, 6), 'hour': random.choice([17, 19, 20]),
#                 'is_hot_match': 0, 'importance': 4, # Importance 4
#                 'price': price, 'total_sold': int(AVG_CAPACITY * fill)
#             })

#         # --- TIER 3: TRUNG BÌNH (Importance 3) ---
#         # Khách hàng: Cân nhắc giá kỹ.
#         for _ in range(200):
#             price = random.randint(100000, 600000)
#             if price <= 200000: fill = random.uniform(0.70, 0.90)
#             elif price <= 350000: fill = random.uniform(0.40, 0.60)
#             else: fill = random.uniform(0.05, 0.20)

#             data.append({
#                 'day_of_week': random.randint(0, 6), 'hour': random.randint(17, 20),
#                 'is_hot_match': 0, 'importance': 3,
#                 'price': price, 'total_sold': int(AVG_CAPACITY * fill)
#             })

#         # --- TIER 4: ĐỘI YẾU / Ế (Importance 1, 2 - VD: Burnley vs Luton) ---
#         # Khách hàng: Chỉ đi xem nếu rẻ như cho.
#         # Giá 290k là CỰC ĐẮT với họ -> Fill rate phải thấp thảm hại.
#         for _ in range(200):
#             price = random.randint(50000, 400000)
#             if price <= 100000: 
#                 fill = random.uniform(0.60, 0.85) # Rẻ bèo mới mua
#             elif price <= 200000: 
#                 fill = random.uniform(0.20, 0.40) # Hơi đắt tí là nghỉ
#             else: 
#                 fill = 0 # Trên 200k là sân trống
            
#             data.append({
#                 'day_of_week': random.randint(0, 6), 'hour': random.randint(14, 17),
#                 'is_hot_match': 0, 
#                 'importance': random.choice([1, 2]), # Importance 1-2
#                 'price': price, 'total_sold': int(AVG_CAPACITY * fill)
#             })

#         # --- 3. TRAIN MODEL ---
#         df = pd.DataFrame(data)
#         X = df[['day_of_week', 'hour', 'is_hot_match', 'importance', 'price']]
#         y = df['total_sold']

#         self.stdout.write(self.style.WARNING('2. Đang huấn luyện trên 100% dữ liệu...'))
        
#         # SỬA LỖI CHÍNH Ở ĐÂY: Dùng RandomForestRegressor + oob_score=True
#         model = RandomForestRegressor(
#             n_estimators=300, 
#             random_state=42, 
#             oob_score=True, # <--- Bật chế độ tự kiểm chứng
#             n_jobs=-1 
#         )
#         model.fit(X, y)

#         # --- 4. IN RA KẾT QUẢ CHỨNG MINH ĐỘ TIN CẬY ---
#         print("\n" + "="*60)
#         print("🔍 ĐỘ TIN CẬY CỦA MODEL (PROOF OF TRUST)")
#         print("="*60)

#         # CHỈ SỐ 1: OOB Score (Thay thế cho R2 Score trên tập Test)
#         # Ý nghĩa: Dự báo chính xác bao nhiêu % trên dữ liệu chưa từng gặp
#         oob_acc = model.oob_score_ * 100
#         print(f"1. ĐỘ CHÍNH XÁC TỔNG QUÁT (OOB Score): {oob_acc:.2f}%")
#         if oob_acc > 80:
#             print("   -> Đánh giá: ✅ XUẤT SẮC (Model dự báo rất sát thực tế)")
#         else:
#             print("   -> Đánh giá: ⚠️ Cần thêm dữ liệu")

#         # CHỈ SỐ 2: Feature Importance (Logic nghiệp vụ)
#         # Ý nghĩa: Model có hiểu quy luật Kinh tế (Giá tăng -> Khách giảm) không?
#         print("\n2. MỨC ĐỘ HIỂU BIẾT NGHIỆP VỤ (Top Factors):")
#         importances = pd.Series(model.feature_importances_, index=X.columns).sort_values(ascending=False)
#         for feature, imp in importances.items():
#             print(f"   - {feature.ljust(15)} : {imp:.1%} ảnh hưởng")

#         print("="*60)

#         # Lưu model
#         save_path = os.path.join(settings.BASE_DIR, 'ml_models')
#         if not os.path.exists(save_path): os.makedirs(save_path)
#         joblib.dump(model, os.path.join(save_path, 'price_optimization_model_1.pkl'))
#         self.stdout.write(self.style.SUCCESS('\n💾 Đã lưu model thành công!'))

# 2
# import pandas as pd
# import joblib
# import os
# import random
# from django.conf import settings
# from django.core.management.base import BaseCommand
# from django.db.models import Avg, Sum
# from sklearn.ensemble import RandomForestRegressor
# # --- THÊM THƯ VIỆN CHIA TẬP VÀ ĐÁNH GIÁ ---
# from sklearn.model_selection import train_test_split
# from sklearn.metrics import mean_absolute_error, r2_score
# # Import Models
# from apps.events.models import Match
# from apps.tickets.models import SectionPrice
# from apps.orders.models import OrderDetail

# class Command(BaseCommand):
#     help = 'Huấn luyện AI với logic Cầu cứng (Inelastic Demand) cho trận HOT'

#     def handle(self, *args, **kwargs):
#         self.stdout.write(self.style.WARNING('1. Đang trích xuất dữ liệu thực tế...'))
        
#         data = []
#         matches = Match.objects.all()
        
#         # 1. LẤY DỮ LIỆU THẬT (REAL DATA)
#         for match in matches:
#             # Lấy giá trung bình
#             avg_price = SectionPrice.objects.filter(match=match).aggregate(Avg('price'))['price__avg']
#             if not avg_price: continue

#             # Lấy tổng vé bán
#             total_sold = OrderDetail.objects.filter(pricing__match=match).count()
            
#             # Lấy tổng sức chứa thực tế của trận này (để tính fill_rate nếu cần normalize)
#             # Nhưng Random Forest có thể học số tuyệt đối nếu quy mô sân tương đồng
            
#             data.append({
#                 'day_of_week': match.match_time.weekday(),
#                 'hour': match.match_time.hour,
#                 'is_hot_match': 1 if match.is_hot_match else 0,
#                 'importance': match.importance,
#                 'price': float(avg_price),
#                 'total_sold': total_sold
#             })

#         # 2. INJECT DỮ LIỆU GIẢ ĐỊNH PHÂN TẦNG (TIERED INJECTION)
#         print("   -> Đang tiêm dữ liệu phân tầng (4 Tiers)...")
        
#         import random
#         AVG_CAPACITY = 1200 

#         # --- TIER 1: SIÊU HOT (Importance 5, Derby) ---
#         # Khách hàng: Bất chấp giá.
#         for _ in range(200):
#             price = random.randint(200000, 2000000)
#             if price <= 800000: fill = random.uniform(0.95, 1.0) # Dưới 800k là auto full
#             elif price <= 1500000: fill = random.uniform(0.70, 0.90)
#             else: fill = random.uniform(0.30, 0.60)
            
#             data.append({
#                 'day_of_week': random.choice([5, 6]), 'hour': random.choice([19, 20]),
#                 'is_hot_match': 1, 'importance': 5,
#                 'price': price, 'total_sold': int(AVG_CAPACITY * fill)
#             })

#         # --- TIER 2: SAO SỐ / CỬA TRÊN (Importance 4 - VD: Man City vs Sheffield) ---
#         # Khách hàng: Chịu chi để xem ngôi sao, nhưng không "điên" như trận Derby.
#         # Giá 300k vẫn phải bán tốt (80-90%), nhưng lên 600k là giảm.
#         for _ in range(200):
#             price = random.randint(150000, 1000000)
#             if price <= 400000: 
#                 fill = random.uniform(0.85, 0.98) # <--- ĐIỂM KHÁC BIỆT: Giá 290k-400k vẫn full
#             elif price <= 700000: 
#                 fill = random.uniform(0.50, 0.75)
#             else: 
#                 fill = random.uniform(0.10, 0.30)

#             data.append({
#                 'day_of_week': random.randint(0, 6), 'hour': random.choice([17, 19, 20]),
#                 'is_hot_match': 0, 'importance': 4, # Importance 4
#                 'price': price, 'total_sold': int(AVG_CAPACITY * fill)
#             })

#         # --- TIER 3: TRUNG BÌNH (Importance 3) ---
#         # Khách hàng: Cân nhắc giá kỹ.
#         for _ in range(200):
#             price = random.randint(100000, 600000)
#             if price <= 200000: fill = random.uniform(0.70, 0.90)
#             elif price <= 350000: fill = random.uniform(0.40, 0.60)
#             else: fill = random.uniform(0.05, 0.20)

#             data.append({
#                 'day_of_week': random.randint(0, 6), 'hour': random.randint(17, 20),
#                 'is_hot_match': 0, 'importance': 3,
#                 'price': price, 'total_sold': int(AVG_CAPACITY * fill)
#             })

#         # --- TIER 4: ĐỘI YẾU / Ế (Importance 1, 2 - VD: Burnley vs Luton) ---
#         # Khách hàng: Chỉ đi xem nếu rẻ như cho.
#         # Giá 290k là CỰC ĐẮT với họ -> Fill rate phải thấp thảm hại.
#         for _ in range(200):
#             price = random.randint(50000, 400000)
#             if price <= 100000: 
#                 fill = random.uniform(0.60, 0.85) # Rẻ bèo mới mua
#             elif price <= 200000: 
#                 fill = random.uniform(0.20, 0.40) # Hơi đắt tí là nghỉ
#             else: 
#                 fill = 0 # Trên 200k là sân trống
            
#             data.append({
#                 'day_of_week': random.randint(0, 6), 'hour': random.randint(14, 17),
#                 'is_hot_match': 0, 
#                 'importance': random.choice([1, 2]), # Importance 1-2
#                 'price': price, 'total_sold': int(AVG_CAPACITY * fill)
#             })

#         # 3. CHUẨN BỊ DỮ LIỆU
#         df = pd.DataFrame(data)
#         X = df[['day_of_week', 'hour', 'is_hot_match', 'importance', 'price']]
#         y = df['total_sold']
        
#         self.stdout.write(f" -> Tổng dữ liệu: {len(df)} mẫu.")

#         # 4. CHIA TRAIN / TEST (80/20)
#         # random_state=42 để kết quả cố định mỗi lần chạy (dễ báo cáo)
#         X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
        
#         self.stdout.write(f" -> Tập Train: {len(X_train)} mẫu | Tập Test: {len(X_test)} mẫu")

#         self.stdout.write(self.style.WARNING('4. Đang huấn luyện trên tập Train...'))
        
#         model = RandomForestRegressor(n_estimators=300, random_state=42, n_jobs=-1)
#         model.fit(X_train, y_train)

#         # 5. ĐÁNH GIÁ ĐỘ TIN CẬY (EVALUATION)
#         self.stdout.write(self.style.WARNING('5. Đang chấm điểm độ tin cậy...'))
        
#         # Dự đoán thử trên tập Test
#         y_pred = model.predict(X_test)
        
#         # Chỉ số 1: MAE (Mean Absolute Error) - Sai số tuyệt đối trung bình
#         # Ý nghĩa: Trung bình AI đoán lệch bao nhiêu vé?
#         mae = mean_absolute_error(y_test, y_pred)
        
#         # Chỉ số 2: R2 Score (Độ phù hợp)
#         # Ý nghĩa: AI giải thích được bao nhiêu % quy luật của dữ liệu (Càng gần 100% càng tốt)
#         r2 = r2_score(y_test, y_pred) * 100

#         print("\n" + "="*50)
#         print("📊 BÁO CÁO HIỆU NĂNG MÔ HÌNH (MODEL PERFORMANCE)")
#         print("="*50)
#         print(f"1. Độ chính xác tổng quát (R2 Score): {r2:.2f}%")
#         if r2 > 80:
#             print("   -> Đánh giá: ✅ RẤT TỐT (Model học được quy luật kinh tế)")
#         elif r2 > 60:
#             print("   -> Đánh giá: ⚠️ KHÁ (Chấp nhận được)")
#         else:
#             print("   -> Đánh giá: ❌ KÉM (Cần xem lại dữ liệu)")
            
#         print(f"2. Sai số trung bình (MAE): {mae:.1f} vé")
#         print(f"   (Trung bình mỗi trận dự đoán lệch khoảng {int(mae)} vé)")
#         print("="*50 + "\n")

#         # Lưu model
#         save_path = os.path.join(settings.BASE_DIR, 'ml_models')
#         if not os.path.exists(save_path): os.makedirs(save_path)
#         joblib.dump(model, os.path.join(save_path, 'price_optimization_model_2.pkl')) # Lưu tên chuẩn
        
#         self.stdout.write(self.style.SUCCESS('💾 Đã lưu model thành công!'))
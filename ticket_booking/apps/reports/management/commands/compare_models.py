# import pandas as pd
# import numpy as np
# import random
# import logging
# from datetime import datetime, timedelta
# from django.core.management.base import BaseCommand
# from django.db.models import Avg
# from sklearn.model_selection import train_test_split
# from sklearn.linear_model import LinearRegression
# from sklearn.ensemble import RandomForestRegressor
# from sklearn.metrics import mean_absolute_error, r2_score
# from prophet import Prophet # Import thư viện mới

# # Tắt log thừa của Prophet cho đỡ rối mắt
# logging.getLogger('cmdstanpy').setLevel(logging.WARNING)
# logging.getLogger('prophet').setLevel(logging.WARNING)

# # Import Models
# from apps.events.models import Match
# from apps.tickets.models import SectionPrice
# from apps.orders.models import OrderDetail

# class Command(BaseCommand):
#     help = 'So sánh 3 mô hình: Linear Regression, Random Forest và Prophet'

#     def handle(self, *args, **kwargs):
#         self.stdout.write(self.style.WARNING('1. Chuẩn bị dữ liệu (Real + Injection)...'))
        
#         data = []
#         matches = Match.objects.all()
        
#         # --- LẤY DỮ LIỆU THẬT ---
#         for match in matches:
#             avg_price = SectionPrice.objects.filter(match=match).aggregate(Avg('price'))['price__avg']
#             if not avg_price: continue
#             total_sold = OrderDetail.objects.filter(pricing__match=match).count()
            
#             data.append({
#                 'day': match.match_time.weekday(), 
#                 'hour': match.match_time.hour,
#                 'hot': 1 if match.is_hot_match else 0, 
#                 'imp': match.importance,
#                 'price': float(avg_price), 
#                 'sold': total_sold
#             })

#         # --- INJECT DỮ LIỆU GIẢ (4 TIERS) ---
#         # Copy y hệt logic inject cũ để công bằng
#         AVG_CAPACITY = 1200
#         # Tier 1 (Siêu Hot)
#         for _ in range(150):
#             price = random.randint(200000, 2000000)
#             fill = 0.95 if price <= 800000 else (0.7 if price <= 1500000 else 0.3)
#             data.append({'day': 5, 'hour': 19, 'hot': 1, 'imp': 5, 'price': price, 'sold': int(AVG_CAPACITY * fill)})

#         # --- TIER 2: SAO SỐ / CỬA TRÊN (Importance 4) ---
#         # Khách chịu chi nhưng không "điên" như Tier 1. 
#         # Giá < 400k vẫn bán tốt, nhưng trên 700k là sụt giảm.
#         for _ in range(150):
#             price = random.randint(150000, 1000000)
#             if price <= 400000: 
#                 fill = random.uniform(0.85, 0.98) 
#             elif price <= 700000: 
#                 fill = random.uniform(0.50, 0.75)
#             else: 
#                 fill = random.uniform(0.10, 0.30)

#             data.append({
#                 'day': random.choice([4, 5, 6]), # Thường đá cuối tuần
#                 'hour': random.choice([17, 19, 20]),
#                 'hot': 0, 
#                 'imp': 4, 
#                 'price': price, 
#                 'sold': int(AVG_CAPACITY * fill)
#             })

#         # --- TIER 3: TRUNG BÌNH (Importance 3) ---
#         # Khách hàng nhạy cảm về giá.
#         for _ in range(150):
#             price = random.randint(100000, 600000)
#             if price <= 200000: 
#                 fill = random.uniform(0.70, 0.90)
#             elif price <= 350000: 
#                 fill = random.uniform(0.40, 0.60)
#             else: 
#                 fill = random.uniform(0.05, 0.20)

#             data.append({
#                 'day': random.randint(0, 6), 
#                 'hour': random.randint(17, 20),
#                 'hot': 0, 
#                 'imp': 3, 
#                 'price': price, 
#                 'sold': int(AVG_CAPACITY * fill)
#             })

#         # ... (Tiếp tục đoạn Tier 4 cũ) ...
#         # Tier 4 (Ế)

#         for _ in range(150):
#             price = random.randint(50000, 400000)
#             fill = 0.8 if price <= 100000 else (0.3 if price <= 200000 else 0)
#             data.append({'day': 0, 'hour': 14, 'hot': 0, 'imp': 1, 'price': price, 'sold': int(AVG_CAPACITY * fill)})

#         df = pd.DataFrame(data)
        
#         # --- CHUẨN BỊ DATA CHO SKLEARN (LR & RF) ---
#         X = df[['day', 'hour', 'hot', 'imp', 'price']]
#         y = df['sold']
#         X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

#         self.stdout.write(f'   -> Tổng mẫu: {len(df)}. Train: {len(X_train)}, Test: {len(X_test)}')

#         # ==========================================
#         # 2. CHẠY CÁC MÔ HÌNH
#         # ==========================================

#         # --- A. Linear Regression ---
#         self.stdout.write(self.style.WARNING('\n2. Đang chạy Linear Regression...'))
#         lr_model = LinearRegression()
#         lr_model.fit(X_train, y_train)
#         y_pred_lr = lr_model.predict(X_test)
#         mae_lr = mean_absolute_error(y_test, y_pred_lr)
#         r2_lr = r2_score(y_test, y_pred_lr)

#         # --- B. Random Forest ---
#         self.stdout.write(self.style.WARNING('3. Đang chạy Random Forest...'))
#         rf_model = RandomForestRegressor(n_estimators=100, random_state=42)
#         rf_model.fit(X_train, y_train)
#         y_pred_rf = rf_model.predict(X_test)
#         mae_rf = mean_absolute_error(y_test, y_pred_rf)
#         r2_rf = r2_score(y_test, y_pred_rf)

#         # --- C. Prophet (Phức tạp hơn xíu) ---
#         self.stdout.write(self.style.WARNING('4. Đang chạy Prophet...'))
        
#         # Prophet cần cột 'ds' (ngày) và 'y' (giá trị). 
#         # Ta phải tạo ngày giả lập từ 'day' (thứ) và 'hour' để Prophet hiểu.
#         df_prophet = df.copy()
#         df_prophet['y'] = df_prophet['sold']
        
#         # Tạo ngày giả: Bắt đầu từ 2024-01-01 + số ngày lệch
#         base_date = datetime(2024, 1, 1)
#         df_prophet['ds'] = df_prophet.apply(
#             lambda row: base_date + timedelta(days=int(row['day']), hours=int(row['hour'])), axis=1
#         )

#         # Chia tập train/test cho Prophet (thủ công vì cấu trúc khác)
#         train_size = int(len(df_prophet) * 0.8)
#         df_p_train = df_prophet.iloc[:train_size]
#         df_p_test = df_prophet.iloc[train_size:]

#         # Cấu hình Prophet
#         # Tắt seasonality tự động, dùng regressors
#         m = Prophet(daily_seasonality=False, weekly_seasonality=False, yearly_seasonality=False)
#         m.add_regressor('price')
#         m.add_regressor('hot')
#         m.add_regressor('imp')
#         # (day và hour đã được gộp vào ds nên không add regressor nữa)

#         m.fit(df_p_train)

#         # Dự báo
#         forecast = m.predict(df_p_test.drop(columns=['y']))
#         y_pred_prophet = forecast['yhat'].values
#         y_true_prophet = df_p_test['y'].values

#         mae_prophet = mean_absolute_error(y_true_prophet, y_pred_prophet)
#         r2_prophet = r2_score(y_true_prophet, y_pred_prophet)

#         # ==========================================
#         # 3. KẾT LUẬN & SO SÁNH
#         # ==========================================
#         print("\n" + "="*60)
#         print(f"{'MÔ HÌNH':<20} | {'SAI SỐ (MAE)':<15} | {'ĐỘ CHÍNH XÁC (R2)':<15}")
#         print("-" * 60)
#         print(f"{'Linear Regression':<20} | {mae_lr:.1f} vé {'(Khá)':<10} | {r2_lr:.3f}")
#         print(f"{'Prophet (Facebook)':<20} | {mae_prophet:.1f} vé {'(Tệ)':<10} | {r2_prophet:.3f}")
#         print(f"{'Random Forest':<20} | {mae_rf:.1f} vé {'(Tốt nhất)':<5} | {r2_rf:.3f}")
#         print("="*60)

#         best_score = max(r2_lr, r2_rf, r2_prophet)
#         if best_score == r2_rf:
#             winner = "Random Forest"
#             reason = "xử lý tốt dữ liệu phi tuyến tính (giá tăng -> khách giảm không đều)."
#         elif best_score == r2_prophet:
#             winner = "Prophet"
#             reason = "xử lý tốt các yếu tố thời gian."
#         else:
#             winner = "Linear Regression"
#             reason = "đơn giản hóa bài toán."

#         self.stdout.write(self.style.SUCCESS(f'\n🏆 KẾT LUẬN: {winner} là mô hình phù hợp nhất cho bài toán này.'))
#         self.stdout.write(f'   Lý do: {reason}')
import pandas as pd
import numpy as np
import random
import logging
from datetime import datetime, timedelta
from django.core.management.base import BaseCommand
from django.db.models import Avg, Sum
from sklearn.model_selection import train_test_split
from sklearn.linear_model import LinearRegression
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, r2_score
from prophet import Prophet 

# Tắt log thừa của Prophet
logging.getLogger('cmdstanpy').setLevel(logging.WARNING)
logging.getLogger('prophet').setLevel(logging.WARNING)

# Import Models
from apps.events.models import Match
from apps.tickets.models import SectionPrice
from apps.orders.models import OrderDetail

class Command(BaseCommand):
    help = 'So sánh độ chính xác giữa Linear Regression, Prophet và Random Forest trên dữ liệu 4 Tiers chuẩn'

    def handle(self, *args, **kwargs):
        self.stdout.write(self.style.WARNING('1. Chuẩn bị dữ liệu (Real + 4 Tiers Injection)...'))
        
        data = []
        matches = Match.objects.all()
        
        # ---------------------------------------------------------
        # A. LẤY DỮ LIỆU THẬT (REAL DATA)
        # ---------------------------------------------------------
        for match in matches:
            avg_price = SectionPrice.objects.filter(match=match).aggregate(Avg('price'))['price__avg']
            if not avg_price: continue
            
            total_sold = OrderDetail.objects.filter(pricing__match=match).count()
            
            data.append({
                'day_of_week': match.match_time.weekday(),
                'hour': match.match_time.hour,
                'is_hot_match': 1 if match.is_hot_match else 0,
                'importance': match.importance,
                'price': float(avg_price),
                'total_sold': total_sold
            })

        # ---------------------------------------------------------
        # B. INJECT DỮ LIỆU GIẢ ĐỊNH PHÂN TẦNG (TIERED INJECTION)
        # (Logic chuẩn từ file train_model để đảm bảo tính nhất quán)
        # ---------------------------------------------------------
        self.stdout.write("   -> Đang tiêm dữ liệu phân tầng (4 Tiers)...")
        
        AVG_CAPACITY = 1200 

        # --- TIER 1: SIÊU HOT (Importance 5) ---
        for _ in range(200):
            price = random.randint(200000, 2000000)
            if price <= 800000: fill = random.uniform(0.95, 1.0)
            elif price <= 1500000: fill = random.uniform(0.70, 0.90)
            else: fill = random.uniform(0.30, 0.60)
            
            data.append({
                'day_of_week': random.choice([5, 6]), 'hour': random.choice([19, 20]),
                'is_hot_match': 1, 'importance': 5,
                'price': price, 'total_sold': int(AVG_CAPACITY * fill)
            })

        # --- TIER 2: SAO SỐ (Importance 4) ---
        for _ in range(200):
            price = random.randint(150000, 1000000)
            if price <= 400000: fill = random.uniform(0.85, 0.98)
            elif price <= 700000: fill = random.uniform(0.50, 0.75)
            else: fill = random.uniform(0.10, 0.30)

            data.append({
                'day_of_week': random.randint(0, 6), 'hour': random.choice([17, 19, 20]),
                'is_hot_match': 0, 'importance': 4,
                'price': price, 'total_sold': int(AVG_CAPACITY * fill)
            })

        # --- TIER 3: TRUNG BÌNH (Importance 3) ---
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

        # --- TIER 4: ĐỘI YẾU / Ế (Importance 1, 2) ---
        for _ in range(200):
            price = random.randint(50000, 400000)
            if price <= 100000: fill = random.uniform(0.60, 0.85)
            elif price <= 200000: fill = random.uniform(0.20, 0.40)
            else: fill = 0 
            
            data.append({
                'day_of_week': random.randint(0, 6), 'hour': random.randint(14, 17),
                'is_hot_match': 0, 
                'importance': random.choice([1, 2]),
                'price': price, 'total_sold': int(AVG_CAPACITY * fill)
            })

        # ---------------------------------------------------------
        # C. CHUẨN BỊ DATASET
        # ---------------------------------------------------------
        df = pd.DataFrame(data)
        X = df[['day_of_week', 'hour', 'is_hot_match', 'importance', 'price']]
        y = df['total_sold']
        
        # Chia tập Train/Test (80/20)
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

        self.stdout.write(f'   -> Tổng mẫu: {len(df)}. Train: {len(X_train)}, Test: {len(X_test)}')

        # =========================================================
        # D. CHẠY SO SÁNH CÁC MÔ HÌNH
        # =========================================================

        # 1. Linear Regression
        self.stdout.write(self.style.WARNING('\n2. Đang chạy Linear Regression...'))
        lr_model = LinearRegression()
        lr_model.fit(X_train, y_train)
        y_pred_lr = lr_model.predict(X_test)
        
        mae_lr = mean_absolute_error(y_test, y_pred_lr)
        r2_lr = r2_score(y_test, y_pred_lr)

        # 2. Random Forest (Cấu hình y hệt script train chính thức)
        self.stdout.write(self.style.WARNING('3. Đang chạy Random Forest...'))
        rf_model = RandomForestRegressor(n_estimators=300, random_state=42) # n_estimators=300
        rf_model.fit(X_train, y_train)
        y_pred_rf = rf_model.predict(X_test)
        
        mae_rf = mean_absolute_error(y_test, y_pred_rf)
        r2_rf = r2_score(y_test, y_pred_rf)

        # 3. Prophet
        self.stdout.write(self.style.WARNING('4. Đang chạy Prophet...'))
        # Prophet cần cột 'ds' (thời gian) và 'y' (target)
        df_prophet = df.copy()
        df_prophet['y'] = df_prophet['total_sold']
        
        # Tạo ngày giả lập để Prophet hiểu (vì ta chỉ có day_of_week)
        base_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        # Tìm thứ 2 của tuần này để làm mốc
        monday = base_date - timedelta(days=base_date.weekday())
        
        df_prophet['ds'] = df_prophet.apply(
            lambda row: monday + timedelta(days=int(row['day_of_week']), hours=int(row['hour'])), axis=1
        )

        train_size = int(len(df_prophet) * 0.8)
        df_p_train = df_prophet.iloc[:train_size]
        df_p_test = df_prophet.iloc[train_size:]

        m = Prophet(daily_seasonality=False, weekly_seasonality=False, yearly_seasonality=False)
        m.add_regressor('price')
        m.add_regressor('is_hot_match')
        m.add_regressor('importance')
        
        m.fit(df_p_train)
        
        # Dự báo
        forecast = m.predict(df_p_test.drop(columns=['y']))
        y_pred_prophet = forecast['yhat'].values
        y_true_prophet = df_p_test['y'].values
        
        mae_prophet = mean_absolute_error(y_true_prophet, y_pred_prophet)
        r2_prophet = r2_score(y_true_prophet, y_pred_prophet)

        # =========================================================
        # E. BÁO CÁO KẾT QUẢ & CHỨNG MINH
        # =========================================================
        print("\n" + "="*70)
        print(f"{'MÔ HÌNH':<20} | {'SAI SỐ (MAE)':<15} | {'ĐỘ CHÍNH XÁC (R2)':<15}")
        print("-" * 70)
        print(f"{'Linear Regression':<20} | {mae_lr:.1f} vé {'':<10} | {r2_lr:.3f} ({r2_lr*100:.1f}%)")
        print(f"{'Prophet (Facebook)':<20} | {mae_prophet:.1f} vé {'':<10} | {r2_prophet:.3f} ({r2_prophet*100:.1f}%)")
        print(f"{'Random Forest':<20} | {mae_rf:.1f} vé {'':<10} | {r2_rf:.3f} ({r2_rf*100:.1f}%)")
        print("="*70)

        # Logic tự động đưa ra kết luận
        best_r2 = max(r2_lr, r2_rf, r2_prophet)
        
        if best_r2 == r2_rf:
            winner = "RANDOM FOREST"
            reason = (
                "Random Forest vượt trội vì khả năng học 'Phi tuyến tính' (Non-linear). \n"
                "   Dữ liệu vé bóng đá có tính chất phân tầng (Tiers): \n"
                "   - Tier 1: Giá cao vẫn mua (Cầu ít co giãn).\n"
                "   - Tier 4: Giá cao chút là bỏ mua (Cầu co giãn mạnh).\n"
                "   => Linear Regression thất bại vì cố vẽ 1 đường thẳng cho tất cả.\n"
                "   => Prophet thất bại vì dữ liệu này không phải chuỗi thời gian liên tục."
            )
        else:
            winner = "Mô hình khác"
            reason = "Cần kiểm tra lại dữ liệu."

        self.stdout.write(self.style.SUCCESS(f'\n🏆 KẾT LUẬN CUỐI CÙNG: {winner} LÀ LỰA CHỌN TỐT NHẤT.'))
        self.stdout.write(f'📝 Lý do khoa học:\n{reason}')
        self.stdout.write(self.style.WARNING('\n-> Khuyến nghị: Sử dụng Random Forest để train model chính thức.'))
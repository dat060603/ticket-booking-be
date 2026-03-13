import pandas as pd
import os
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

# Import Models (Đảm bảo đường dẫn import đúng với dự án của bạn)
from apps.events.models import Match
from apps.tickets.models import SectionPrice
from apps.orders.models import OrderDetail

class Command(BaseCommand):
    help = 'Xuất dữ liệu mẫu từ Database ra file Excel (Match, SectionPrice, OrderDetail)'

    def handle(self, *args, **kwargs):
        self.stdout.write(self.style.WARNING('⏳ Đang bắt đầu xuất dữ liệu...'))

        # --- 1. LẤY DỮ LIỆU TỪ DB ---
        matches_qs = Match.objects.all().values(
            'match_id', 'league__league_name', 'team_1__team_name', 
            'team_2__team_name', 'match_time', 'stadium__stadium_name',
            'is_hot_match', 'importance'
        )
        
        prices_qs = SectionPrice.objects.all().values(
            'pricing_id', 'match__match_id', 'section__section_name',
            'price', 'available_seats'
        )

        orders_qs = OrderDetail.objects.all().values(
            'detail_id', 'order__order_id', 'pricing__pricing_id',
            'price', 'seat__seat_number', 'updated_at'
        )

        # --- 2. CHUYỂN ĐỔI SANG DATAFRAME ---
        df_match = pd.DataFrame(list(matches_qs))
        df_price = pd.DataFrame(list(prices_qs))
        df_order = pd.DataFrame(list(orders_qs))

        # Đổi tên cột (Optional)
        if not df_match.empty:
            df_match.rename(columns={
                'league__league_name': 'Giải đấu',
                'team_1__team_name': 'Đội 1',
                'team_2__team_name': 'Đội 2',
                'match_time': 'Thời gian'
            }, inplace=True)
            # Xử lý múi giờ
            if 'Thời gian' in df_match.columns:
                df_match['Thời gian'] = df_match['Thời gian'].apply(lambda x: x.replace(tzinfo=None) if x else None)
        
        if not df_order.empty and 'updated_at' in df_order.columns:
            df_order['updated_at'] = df_order['updated_at'].apply(lambda x: x.replace(tzinfo=None) if x else None)

        # --- 3. XUẤT RA FILE EXCEL ---
        file_name = 'sample_data_export.xlsx'
        file_path = os.path.join(settings.BASE_DIR, file_name)

        try:
            with pd.ExcelWriter(file_path, engine='openpyxl') as writer:
                if not df_match.empty:
                    df_match.to_excel(writer, sheet_name='Matches', index=False)
                else:
                    pd.DataFrame(['No Data']).to_excel(writer, sheet_name='Matches')

                if not df_price.empty:
                    df_price.to_excel(writer, sheet_name='SectionPrices', index=False)
                else:
                    pd.DataFrame(['No Data']).to_excel(writer, sheet_name='SectionPrices')

                if not df_order.empty:
                    df_order.to_excel(writer, sheet_name='OrderDetails', index=False)
                else:
                    pd.DataFrame(['No Data']).to_excel(writer, sheet_name='OrderDetails')

            self.stdout.write(self.style.SUCCESS(f'✅ Xuất thành công! File tại: {file_path}'))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'❌ Lỗi: {str(e)}'))
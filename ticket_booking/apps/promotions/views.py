
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated, IsAdminUser, AllowAny
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter
from .models import Promotion
from apps.orders.models import OrderDetail
from .serializers import PromotionSerializer
from apps.tickets.serializers import SectionSerializer
from apps.tickets.models import Section
from apps.events.models import Match
from django.utils import timezone
from django.shortcuts import get_object_or_404
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from rest_framework.decorators import action
from rest_framework import status
from rest_framework.views import APIView
from .tasks import set_promotion_status

class PromotionViewSet(viewsets.ModelViewSet):
    """
    API CRUD cho Promotion, có nested PromotionDetail qua 'lines'
    """
    queryset = Promotion.objects.all().order_by('-end_time')
    serializer_class = PromotionSerializer
    permission_classes = [AllowAny]
    filter_backends = [DjangoFilterBackend, SearchFilter]
    filterset_fields = ['status']
    search_fields = ['promo_code', 'description']

    def list(self, request, *args, **kwargs):
        now = timezone.now()
        # Promotion.objects.filter(status=True, end_time__lt=now).update(status=False)

        return super().list(request, *args, **kwargs)
    
    @action(detail=False, methods=['patch'])
    def bulk_toggle(self, request):
        """
        PATCH /api/promotions/bulk_toggle/
        body: { "ids": [1,2,3], "status": true }
        """
        ids = request.data.get('ids', [])
        new_status = request.data.get('status')

        if not isinstance(ids, list) or new_status is None:
            return Response(
                {'detail': 'ids và status là bắt buộc.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        now = timezone.now()
        qs = Promotion.objects.filter(promo_id__in=ids)
        
        # Kiểm tra xem có promotion nào đã hết hạn không
        expired = qs.filter(end_time__lt=now).values_list('promo_id', flat=True)
        if expired:
            return Response(
                {
                    'detail': 'Không thể thay đổi trạng thái cho các mã đã hết hạn.',
                    'expired_ids': list(expired)
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        updated = qs.update(status=new_status)
        return Response({'updated': updated}, status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        try:
            result = PromotionSerializer.delete_instance(instance)
            return Response(result, status=status.HTTP_200_OK)
        except ValidationError as e:
            return Response({"detail": e.detail}, status=status.HTTP_400_BAD_REQUEST)
        
    def perform_create(self, serializer):
        promo = serializer.save()
        # Đặt lịch bật vào đúng thời điểm start_time
        set_promotion_status.apply_async(
            args=[promo.promo_id, True],
            eta=promo.start_time
        )
        # Đặt lịch tắt vào đúng thời điểm end_time
        set_promotion_status.apply_async(
            args=[promo.promo_id, False],
            eta=promo.end_time
        )

    def perform_update(self, serializer):
        promo = serializer.save()
        # Nếu admin thay đổi start/end time, hủy/bỏ task cũ (nếu cần),
        # rồi đặt lại lịch mới
        set_promotion_status.apply_async(
            args=[promo.promo_id, True],
            eta=promo.start_time
        )
        set_promotion_status.apply_async(
            args=[promo.promo_id, False],
            eta=promo.end_time
        )
    
    

# Lấy danh sách section theo match
class SectionListAPIView_Promotions(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        match_id = request.query_params.get('match')
        if match_id:
            match = get_object_or_404(Match, pk=match_id)
            sections = Section.objects.filter(stadium=match.stadium)
        else:
            sections = Section.objects.all()

        serializer = SectionSerializer(sections, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
# Lấy danh sách trận đấu
class MatchListAPIView_Promotions(APIView):
    def get(self, request):
        now = timezone.now()
        matches = Match.objects.filter(match_time__gt=now)

        result = [
            {
                "match_id": match.match_id,
                "display": str(match),
                "match_time": match.match_time,
                "match_time_fmt": match.match_time.strftime("%d %b %Y, %H:%M"),
                "stadium_id": match.stadium_id
            }
            for match in matches
        ]

        return Response(result, status=status.HTTP_200_OK)


# AI TẠO PROMOTION
import joblib
import os
import numpy as np
from django.conf import settings
from django.db.models import Sum, Avg
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response

# Import Models
from apps.events.models import Match
from apps.tickets.models import SectionPrice, Section, Seat

class AnalyzePromotionEffectivenessView(APIView):
    """
    API Phân tích Khuyến mãi: Tối ưu giá (AI Pricing Strategist).
    Phiên bản: FINAL FIXED
    Input: {"match_id":2}
    """
    def post(self, request):
        match_id = request.data.get('match_id')
        if not match_id:
            return Response({"error": "Thiếu match_id"}, status=400)

        try:
            match = Match.objects.get(pk=match_id)
            
            # ==========================================
            # 0. TÍNH THỜI GIAN
            # ==========================================
            now = timezone.now()
            days_left = (match.match_time - now).days
            
            if days_left < 0:
                 return Response({"error": "Trận đấu đã kết thúc/đang diễn ra."}, status=400)

            # ==========================================
            # 1. LẤY DỮ LIỆU INVENTORY
            # ==========================================
            open_prices = SectionPrice.objects.filter(match=match)
            if not open_prices.exists():
                return Response({"error": "Trận đấu chưa mở bán vé nào."}, status=400)

            open_sections = Section.objects.filter(tickets__in=open_prices).distinct()
            total_capacity_open = open_sections.aggregate(t=Sum('capacity'))['t'] or 0
            maintenance_count = Seat.objects.filter(section__in=open_sections, status=1).count()
            initial_supply = total_capacity_open - maintenance_count
            
            if initial_supply <= 0:
                return Response({"error": "Supply = 0"}, status=400)

            price_agg = open_prices.aggregate(
                total_avail=Sum('available_seats'),
                avg_price=Avg('price')
            )
            current_available = price_agg['total_avail'] or 0
            current_price = float(price_agg['avg_price'] or 0)

            current_sold = initial_supply - current_available
            if current_sold < 0: current_sold = 0
            
            fill_rate_now = (current_sold / initial_supply) * 100

            if fill_rate_now > 98:
                return Response({
                    "status": "warning",
                    "message": f"Trận này đã bán {fill_rate_now:.1f}% (Sold-out). Không cần khuyến mãi."
                })

            # ==========================================
            # 2. CHUẨN BỊ AI MODEL
            # ==========================================
            model_path = os.path.join(settings.BASE_DIR, 'ml_models', 'price_optimization_model_2.pkl')
            model = joblib.load(model_path)

            day = match.match_time.weekday()
            hour = match.match_time.hour
            is_hot = 1 if match.is_hot_match else 0
            importance = match.importance

            match_tier = "Tier 3 (Bình thường)"
            if importance == 5 or (importance == 4 and is_hot): match_tier = "Tier 1 (Siêu HOT)"
            elif importance == 4: match_tier = "Tier 2 (Trận nổi bậc)"
            elif importance <= 2: match_tier = "Tier 4 (Trận kém thu hút)"

            # ==========================================
            # 3. MÔ PHỎNG CHIẾN LƯỢC
            # ==========================================
            discounts = [0, 5, 10, 15, 20, 25, 30, 40, 50]
            best_option = None
            max_revenue = -1
            analysis = []

            # --- A. XÁC ĐỊNH TRẠNG THÁI ---
            critical_threshold = 40 
            if "Tier 1" in match_tier: critical_threshold = 60
            elif "Tier 2" in match_tier: critical_threshold = 50

            is_critical_state = False
            is_warning_state = False

            if days_left <= 3 and fill_rate_now < critical_threshold:
                is_critical_state = True
            elif days_left <= 10 and fill_rate_now < (critical_threshold + 10):
                is_warning_state = True

            # --- B. BASE FACTOR ---
            reality_base = 1.0
            if is_critical_state: reality_base = 0.2
            elif is_warning_state: reality_base = 0.6
            elif "Tier 4" in match_tier and fill_rate_now < 20: reality_base = 0.4

            time_pressure_factor = 1.0
            if days_left > 14: time_pressure_factor = 0.9
            elif is_critical_state: time_pressure_factor = 0.5
            elif is_warning_state: time_pressure_factor = 0.8

            base_factor = reality_base * time_pressure_factor

            # --- C. VÒNG LẶP MÔ PHỎNG ---
            for pct in discounts:
                promo_price = current_price * (1 - pct / 100)
                features = np.array([[day, hour, is_hot, importance, promo_price]])
                predicted_raw = int(model.predict(features)[0])
                
                # --- [FIX 1] ĐIỀU CHỈNH ĐỘ NHẠY CHO TIER 4 (Áp dụng cả Warning State) ---
                sensitivity = 0.8 
                penalty_for_weak_discount = 1.0

                if "Tier 4" in match_tier and (is_critical_state or is_warning_state):
                    # Tier 4 mà đang ế (kể cả còn 6 ngày hay 2 ngày) thì khách rất chảnh
                    if pct < 25: 
                        sensitivity = 0.1 # Giảm ít -> Không ai quan tâm
                        penalty_for_weak_discount = 0.3 # Phạt nặng
                    else:
                        sensitivity = 3.5 # Giảm sâu -> Mới bắt đầu quan tâm
                
                elif is_critical_state:
                    sensitivity = 3.0 # Tier 1,2,3 gấp thì FOMO
                elif is_warning_state:
                    sensitivity = 1.2

                # Tính Factor
                boost_from_discount = (pct / 100) * sensitivity 
                current_base_factor = base_factor * penalty_for_weak_discount
                adjusted_factor = current_base_factor + boost_from_discount
                
                if adjusted_factor > 1.5: adjusted_factor = 1.5
                
                predicted_demand = int(predicted_raw * adjusted_factor)
                
                # --- [FIX 2] VELOCITY CAP (Mở rộng phạm vi lên 7 ngày) ---
                # Nếu Tier 4 đang ế nặng, dù còn 7 ngày cũng không thể bán 100% vé trong tích tắc nếu giảm giá thấp
                
                if days_left <= 7 and fill_rate_now < 20:
                    # Cap phụ thuộc vào mức giảm giá
                    # 10% -> Max bán được 20% tổng cung
                    # 50% -> Max bán được 80% tổng cung
                    velocity_cap_percent = 0.1 + (pct / 100) * 1.4 
                    
                    max_sellable_amount = initial_supply * velocity_cap_percent
                    if predicted_demand > max_sellable_amount:
                        predicted_demand = int(max_sellable_amount)

                # -----------------------------------------------------------

                potential_new = predicted_demand - current_sold
                if potential_new < 0: potential_new = 0
                
                sales_new = min(potential_new, current_available)
                revenue_scenario = sales_new * promo_price
                new_fill_rate = ((current_sold + sales_new) / initial_supply) * 100

                sim_result = {
                    "discount": pct,
                    "promo_price": promo_price,
                    "extra_sold": sales_new,
                    "extra_revenue": revenue_scenario,
                    "final_fill_rate": round(new_fill_rate, 1)
                }
                analysis.append(sim_result)

                if revenue_scenario > max_revenue:
                    max_revenue = revenue_scenario
                    best_option = sim_result

            # ==========================================
            # 4. TRẢ KẾT QUẢ
            # ==========================================
            return Response({
                "status": "success",
                "match_info": {
                    "name": f"{match.team_1} vs {match.team_2}",
                    "tier": match_tier,
                    "days_left": days_left,
                    "sold_real": current_sold,
                    "initial_supply": initial_supply,
                    "available_real": current_available,
                    "fill_rate": round(fill_rate_now, 1)
                },
                "recommendation": {
                    "best_discount": best_option['discount'],
                    "expected_extra_revenue": best_option['extra_revenue'],
                    "expected_extra_sold": best_option['extra_sold'],
                    "final_fill_rate": best_option['final_fill_rate'],
                    "message": self.generate_message(best_option, match_tier, days_left, is_critical_state, is_warning_state)
                },
                "analysis_data": analysis
            })

        except Exception as e:
            return Response({"error": str(e)}, status=500)

    def generate_message(self, opt, tier, days, is_critical, is_warning):
        status_msg = ""
        if is_critical: status_msg = f"CẢNH BÁO ĐỎ (Còn {days} ngày, chưa đạt KPI). "
        elif is_warning: status_msg = f"CẢNH BÁO VÀNG (Còn {days} ngày, bán chậm). "
        else: status_msg = f"Tình hình ổn định (Còn {days} ngày). "
        
        if opt['discount'] == 0:
            return f"{status_msg}Trận '{tier}'. Giá hiện tại đang tối ưu."
        
        action = "xả hàng tồn kho" if (is_critical or is_warning) and "Tier 4" in tier else "kích cầu"
        return (f"{status_msg}AI đề xuất mức giảm {opt['discount']}% để {action} cho trận '{tier}', "
                f"dự kiến kéo thêm {opt['extra_sold']} khán giả.")
from django.shortcuts import render, get_object_or_404
from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.decorators import api_view
from .models import Section, Seat, SectionPrice, PriceHistory
from .serializers import SectionSerializer, SeatSerializer, SectionPriceSerializer
from .serializers import SectionPriceDetailSerializer, MatchNoTicketSerializer
from rest_framework.permissions import AllowAny
from ..events.models import Match
from decimal import Decimal
from datetime import datetime
from .serializers import MatchDetailSerializer
from .serializers import PriceHistorySerializer
from rest_framework.views import APIView
class SectionViewSet(viewsets.ModelViewSet):
    queryset = Section.objects.all()
    serializer_class = SectionSerializer
    permission_classes = [AllowAny]

class SeatViewSet(viewsets.ModelViewSet):
    queryset = Seat.objects.all()
    serializer_class = SeatSerializer
    permission_classes = [AllowAny]

from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework import status
from .models import SectionPrice
from .serializers import SectionPriceSerializer
from rest_framework.permissions import  AllowAny


class SectionPriceViewSet(viewsets.ModelViewSet):
    queryset = SectionPrice.objects.all()
    serializer_class = SectionPriceSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        """Allow filtering by sport_id or sport_name via query params."""
        qs = SectionPrice.objects.all().select_related('match__league__sport', 'section')
        sport_id = self.request.query_params.get('sport_id')
        sport_name = self.request.query_params.get('sport_name')
        if sport_id:
            try:
                sid = int(sport_id)
                qs = qs.filter(match__league__sport__sport_id=sid)
            except ValueError:
                pass
        if sport_name:
            qs = qs.filter(match__league__sport__sport_name__icontains=sport_name)
        return qs

    @action(detail=True, methods=['patch'], url_path='stop_selling')
    def stop_selling(self, request, pk=None):
        section_price = self.get_object()
        section_price.is_closed = True
        section_price.save()
        return Response({'status': 'Vé đã được dừng bán'}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['patch'], url_path='reopen_selling')
    def reopen_selling(self, request, pk=None):
        section_price = self.get_object()
        section_price.is_closed = False
        section_price.save()
        return Response({'status': 'Vé đã được mở bán lại'}, status=status.HTTP_200_OK)


from rest_framework.response import Response
from rest_framework import status, viewsets
from .models import SectionPrice, PriceHistory
from .serializers import PriceHistorySerializer
from django.utils import timezone
from .tasks import apply_price_change
from django.utils.dateparse import parse_datetime
from rest_framework.permissions import AllowAny
from django.utils.timezone import make_aware, is_naive
from .tasks import apply_price_change, close_section_before_price_change

class PriceHistoryViewSet(viewsets.ModelViewSet):
    queryset = PriceHistory.objects.all()
    serializer_class = PriceHistorySerializer
    permission_classes = [AllowAny]

    def create(self, request, *args, **kwargs):
        pricing_id = request.data.get('pricing')
        new_price = request.data.get('new_price')
        effective_date = request.data.get('effective_date')

        try:
            section_price = SectionPrice.objects.select_related('match').get(pk=pricing_id)
        except SectionPrice.DoesNotExist:
            return Response({'error': 'SectionPrice not found.'}, status=status.HTTP_404_NOT_FOUND)

        old_price = section_price.price

        history_data = {
            'pricing': pricing_id,
            'new_price': new_price,
            'effective_date': effective_date,
            'changed_by': request.data.get('changed_by'),
            'reason': request.data.get('reason')
        }

        serializer = self.get_serializer(data=history_data)
        serializer.is_valid(raise_exception=True)
        serializer.save(old_price=old_price)

        saved_history = serializer.instance
        effective_datetime = parse_datetime(effective_date)

        if effective_datetime and is_naive(effective_datetime):
            effective_datetime = make_aware(effective_datetime)

        now = timezone.now()

        if effective_datetime > now:
            # Áp dụng sau: lên lịch với Celery
            apply_price_change.apply_async((saved_history.pk,), eta=effective_datetime)
            close_time = effective_datetime - timezone.timedelta(minutes=1)
            close_section_before_price_change.apply_async((saved_history.pk,), eta=close_time)
        else:
            # Áp dụng ngay lập tức
            section_price.price = new_price
            section_price.sell_date = effective_datetime

            # ✅ Đảm bảo match_time là aware trước khi so sánh
            match_time = section_price.match.match_time
            if is_naive(match_time):
                match_time = make_aware(match_time)

            if match_time <= effective_datetime:
                section_price.is_closed = True
            else:
                section_price.is_closed = False

            section_price.save(update_fields=['price', 'sell_date', 'is_closed'])


        return Response(serializer.data, status=status.HTTP_201_CREATED)






# ds trận chưa tạo vé
from django.utils.timezone import now

class MatchWithoutTicketsViewSet(viewsets.ViewSet):
    permission_classes = [AllowAny]

    def list(self, request):
        all_matches = Match.objects.all()
        matches_with_missing_prices = []
        completed_matches = []

        current_time = now()

        for match in all_matches:
            # Trận đã kết thúc
            if match.match_time < current_time:
                completed_matches.append(match)
                continue

            # Kiểm tra còn khu vực nào chưa có vé
            sections = Section.objects.filter(stadium=match.stadium)
            section_ids = sections.values_list('section_id', flat=True)

            priced_sections = SectionPrice.objects.filter(match=match).values_list('section_id', flat=True)

            if set(section_ids) - set(priced_sections):
                matches_with_missing_prices.append(match)

        return Response({
            'status': 'success',
            'matches_with_missing_prices': MatchNoTicketSerializer(matches_with_missing_prices, many=True).data,
            'completed_matches': MatchNoTicketSerializer(completed_matches, many=True).data
        }, status=status.HTTP_200_OK)

    
from datetime import datetime
from rest_framework.response import Response
from rest_framework.decorators import api_view
from .models import Match, Section, SectionPrice
from decimal import Decimal
from rest_framework import status
from django.shortcuts import get_object_or_404
from django.utils import timezone

@api_view(['POST'])
def create_section_price(request, match_id, section_id):
    match = get_object_or_404(Match, match_id=match_id)
    section = get_object_or_404(Section, section_id=section_id)

    try:
        data = request.data
        price = Decimal(data.get('price'))

        # Parse sell_date từ định dạng ISO
        sell_date_str = data.get('sell_date')
        sell_date = datetime.fromisoformat(sell_date_str)

        # Đảm bảo sell_date và now đều là datetime aware
        if timezone.is_naive(sell_date):
            sell_date = timezone.make_aware(sell_date)

        # Kiểm tra timezone của now
        now = timezone.now()

        # Đảm bảo now cũng là datetime aware
        if timezone.is_naive(now):
            now = timezone.make_aware(now)

        # Kiểm tra giá trị của sell_date và now
        print(f"sell_date: {sell_date}, now: {now}")

        # Kiểm tra nếu sell_date > now, is_closed = True, ngược lại = False
        is_closed = sell_date > now

        # In ra giá trị của is_closed để kiểm tra
        print(f"Before saving: is_closed = {is_closed}")

        # Tạo SectionPrice mới với is_closed luôn True nếu sell_date > now
        section_price = SectionPrice(
            match=match,
            section=section,
            price=price,
            available_seats=int(data.get('available_seats')),
            is_closed=True,  # Đảm bảo luôn True
            sell_date=sell_date
        )

        # Kiểm tra trước khi save
        print(f"SectionPrice instance before save: {section_price}")

        section_price.save()

        # In ra giá trị is_closed sau khi save
        print(f"✅ is_closed saved: {section_price.is_closed}")

        # Tạo serializer để trả về response
        serializer = SectionPriceDetailSerializer(section_price)
        return Response({
            'status': 'success',
            'message': 'Pricing added successfully',
            'data': serializer.data
        }, status=status.HTTP_201_CREATED)

    except Exception as e:
        return Response({'status': 'error', 'message': str(e)}, status=status.HTTP_400_BAD_REQUEST)








# chọn trận đấu để tạo vé 
class MatchDetailView(APIView):
    def get(self, request, match_id):
        try:
            match = Match.objects.get(match_id=match_id)
            sections = Section.objects.filter(stadium=match.stadium)

            section_data = []
            for section in sections:
                try:
                    section_price = SectionPrice.objects.get(match=match, section=section)
                    section_data.append({
                        "section_id": section.section_id,
                        "section_name": section.section_name,
                        "has_price": True,
                        "pricing_id": section_price.pricing_id,
                        "price": section_price.price,
                        "available_seats": section_price.available_seats,
                        "sell_date": section_price.sell_date,
                        "is_closed": section_price.is_closed
                    })
                except SectionPrice.DoesNotExist:
                    # Tính toán available_seats = tổng số ghế trong section - số ghế bị bảo trì
                    total_seats = section.seat_set.count()  # Tổng số ghế trong section
                    maintenance_seats = section.seat_set.filter(status=1).count()  # Số ghế bị bảo trì
                    available_seats = total_seats - maintenance_seats  # Số ghế khả dụng

                    # Trả về thông tin section khi chưa có giá vé, bao gồm cả số ghế khả dụng
                    section_data.append({
                        "section_id": section.section_id,
                        "section_name": section.section_name,
                        "has_price": False,
                        "available_seats": available_seats  # Tính toán số ghế khả dụng
                    })

            data = {
                "match_id": match.match_id,
                "description": match.description,
                "match_time": match.match_time,  
                "stadium_name": match.stadium.stadium_name,
                "sections": section_data
            }
            return Response(data, status=200)

        except Match.DoesNotExist:
            return Response({"error": "Match not found"}, status=404)



# lấy ds các trận đã tạo xog vé
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from apps.events.models import Match, Stadium
from apps.tickets.models import Section, SectionPrice
from apps.tickets.serializers import MatchSimpleSerializer

class CompletedTicketMatchesAPIView(APIView):
    def get(self, request):
        completed_matches = []

        # Hỗ trợ lọc theo sport_id hoặc sport_name qua query params
        sport_id = request.query_params.get('sport_id')
        sport_name = request.query_params.get('sport_name')

        # Select related league and sport to avoid N+1 queries
        all_matches = Match.objects.select_related('stadium', 'league__sport').all()

        if sport_id:
            try:
                sport_id_int = int(sport_id)
                all_matches = all_matches.filter(league__sport__sport_id=sport_id_int)
            except ValueError:
                # ignore invalid sport_id
                pass
        elif sport_name:
            all_matches = all_matches.filter(league__sport__sport_name__icontains=sport_name)

        for match in all_matches:
            # Kiểm tra nếu match không có sân vận động hợp lệ
            if not match.stadium:
                continue

            stadium_sections = Section.objects.filter(stadium=match.stadium)
            section_ids = stadium_sections.values_list('section_id', flat=True)

            section_prices = SectionPrice.objects.filter(match=match, section_id__in=section_ids)
            if stadium_sections.exists() and section_prices.count() == stadium_sections.count():
                completed_matches.append(match)

        serializer = MatchSimpleSerializer(completed_matches, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

# lấy section theo trận có stadium
class MatchSectionPricesAPIView(APIView):
    def get(self, request, match_id):
        try:
            match = Match.objects.get(pk=match_id)
        except Match.DoesNotExist:
            return Response({"detail": "Match not found."}, status=status.HTTP_404_NOT_FOUND)

        section_prices = SectionPrice.objects.filter(match=match).select_related('section')
        serializer = SectionPriceSerializer(section_prices, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
# xóa section_price
# views.py
# from rest_framework.views import APIView
# from rest_framework.response import Response
# from rest_framework import status
# from .models import SectionPrice
# class DeleteSectionPriceView(APIView):
#     def delete(self, request, pricing_id):
#         try:
#             section_price = SectionPrice.objects.get(pricing_id=pricing_id)

#             if section_price.is_closed:
#                 section_price.delete()
#                 return Response({"message": "Giá vé đã được xóa thành công."}, status=status.HTTP_204_NO_CONTENT)
#             else:
#                 return Response(
#                     {"error": "Không thể xóa vì vé đã được mở bán."},
#                     status=status.HTTP_400_BAD_REQUEST
#                 )

#         except SectionPrice.DoesNotExist:
#             return Response({"error": "Không tìm thấy thông tin giá vé."}, status=status.HTTP_404_NOT_FOUND)
# AI GIÁ


# AI 2
import joblib
import os
import numpy as np
from django.utils import timezone
from django.conf import settings
from django.db.models import Sum # Đạt nhớ thêm import Sum nhé
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

# Import Models
from apps.events.models import Match

class SuggestOptimalPriceView(APIView):
    """
    API Đề xuất giá vé tối ưu (AI Dynamic Pricing).
    Logic: 
    1. Dự báo nhu cầu bằng Random Forest (Ensemble).
    2. Đo lường độ tin cậy bằng độ lệch chuẩn giữa các cây (Standard Deviation).
    3. Cân bằng giữa Doanh thu (70%) và Tỷ lệ lấp đầy (30%).
    """
    def post(self, request):
        try:
            # 1. Kiểm tra Input
            match_id = request.data.get('match_id')
            if not match_id:
                return Response({"error": "Vui lòng cung cấp ID trận đấu (match_id)"}, status=status.HTTP_400_BAD_REQUEST)

            # 2. Lấy thông tin trận đấu
            try:
                match = Match.objects.select_related('stadium', 'team_1', 'team_2').get(pk=match_id)
            except Match.DoesNotExist:
                return Response({"error": "Trận đấu không tồn tại"}, status=status.HTTP_404_NOT_FOUND)

            if match.match_time < timezone.now():
                return Response({"error": "Trận đấu đã diễn ra, không thể gợi ý giá."}, status=status.HTTP_400_BAD_REQUEST)

            # 3. Chuẩn bị dữ liệu cho AI
            day_of_week = match.match_time.weekday()
            hour = match.match_time.hour
            is_hot_match = 1 if match.is_hot_match else 0
            importance = match.importance

            # Lấy sức chứa sân
            real_capacity = 0
            if hasattr(match.stadium, 'sections'):
                real_capacity = match.stadium.sections.aggregate(Sum('capacity'))['capacity__sum'] or 0
            MAX_CAPACITY = real_capacity if real_capacity > 0 else (match.stadium.capacity or 500)

            # 4. Load Model AI
            # LƯU Ý: Đảm bảo tên file model khớp với file bạn vừa train (có thể là _1.pkl)
            model_path = os.path.join(settings.BASE_DIR, 'ml_models', 'price_optimization_model.pkl')
            
            # Nếu bạn dùng tên file mới thì đổi dòng trên thành:
            # model_path = os.path.join(settings.BASE_DIR, 'ml_models', 'price_optimization_model_1.pkl')

            if not os.path.exists(model_path):
                return Response({"error": "Chưa train model AI."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
            
            model = joblib.load(model_path)

            # 5. THIẾT LẬP KHOẢNG QUÉT GIÁ (SCAN RANGE)
            min_price = 50000
            
            if is_hot_match or importance == 5:
                max_price = 1500000 
            elif importance == 4:
                max_price = 700000
            elif importance == 3:
                max_price = 500000
            else:
                max_price = 300000 

            price_range = range(min_price, max_price + 20000, 20000) 

            # 6. VÒNG LẶP GIẢ LẬP
            simulations = []
            max_revenue_found = 0 
            estimators = model.estimators_ 

            for p in price_range:
                features = np.array([[day_of_week, hour, is_hot_match, importance, p]])
                
                # Lấy dự báo từ 300 cây
                tree_predictions = [tree.predict(features)[0] for tree in estimators]
                
                pred_qty_avg = np.mean(tree_predictions)
                pred_std = np.std(tree_predictions)
                
                # --- SỬA CÔNG THỨC TẠI ĐÂY ---
                # Tính độ lệch tương đối so với sức chứa sân (Relative Variance)
                if MAX_CAPACITY > 0:
                    variance_ratio = pred_std / MAX_CAPACITY
                else:
                    variance_ratio = 1
                penalty_factor = 60 if MAX_CAPACITY < 2000 else 120
                # Công thức mới: Phạt dựa trên % sai số so với sức chứa
                # Hệ số phạt 300 nghĩa là: Nếu độ lệch > 33% sức chứa thì điểm về 0
                # Ví dụ: Sân 1000, lệch 100 (10%) -> 100 - (0.1 * 300) = 70 điểm (Khá)
                #        Sân 1000, lệch 300 (30%) -> 100 - (0.3 * 300) = 10 điểm (Thấp)

                confidence_score = max(0, 100 - (variance_ratio * penalty_factor))

                # -----------------------------

                pred_qty = int(max(0, min(pred_qty_avg, MAX_CAPACITY)))
                
                revenue = pred_qty * p
                fill_rate = (pred_qty / MAX_CAPACITY) * 100

                if revenue > max_revenue_found:
                    max_revenue_found = revenue

                simulations.append({
                    "price": p,
                    "revenue": revenue,
                    "sold": pred_qty,
                    "fill_rate": round(fill_rate, 1),
                    "confidence": round(confidence_score, 1) # Điểm số giờ sẽ hợp lý hơn
                })

            # 7. CHẤM ĐIỂM TÌM PHƯƠNG ÁN TỐI ƯU (SCORING)
            best_option = None
            best_score = -9999
            
            chart_data = [] 

            for sim in simulations:
                chart_data.append(sim)
                if sim['sold'] <= 0: continue

                # Score = (Revenue_Score * 0.7) + (Fill_Rate_Score * 0.3)
                rev_score = (sim['revenue'] / max_revenue_found) * 100 if max_revenue_found > 0 else 0
                fill_score = sim['fill_rate']
                
                final_score = (rev_score * 0.7) + (fill_score * 0.3)
                
                if sim['fill_rate'] < 40:
                    final_score -= 30

                sim['score'] = round(final_score, 1)

                if final_score > best_score:
                    best_score = final_score
                    best_option = sim

            if not best_option:
                best_option = simulations[0]

            # 8. XỬ LÝ MESSAGE ĐỘ TIN CẬY (Để hiển thị cho Admin)
            conf_val = best_option.get('confidence', 0)
            if conf_val >= 75:
                conf_level = "CAO (High)"
                conf_msg = "AI khá  tự tin với phương án này (Dữ liệu đồng thuận cao)."
            elif conf_val >= 50:
                conf_level = "TRUNG BÌNH (Medium)"
                conf_msg = "Dữ liệu có biến động, Admin nên cân nhắc thêm."
            else:
                conf_level = "THẤP (Low)"
                conf_msg = "Dữ liệu bất thường (Outlier), AI không chắc chắn."

            # 9. TRẢ VỀ KẾT QUẢ
            return Response({
                "status": "success",
                "match_info": {
                    "match_id": match.match_id,
                    "name": f"{match.team_1.team_name} vs {match.team_2.team_name}",
                    "time": match.match_time,
                    "is_hot": match.is_hot_match,
                    "importance": match.importance,
                    "stadium_capacity": MAX_CAPACITY
                },
                "recommendation": {
                    "optimal_avg_price": best_option['price'],
                    "estimated_revenue": best_option['revenue'],
                    "estimated_sold": best_option['sold'],
                    "fill_rate": best_option['fill_rate'],
                    "reason": self.generate_reason(best_option, match.is_hot_match),
                    
                    # --- THÔNG TIN THÊM CHO ADMIN ---
                    "ai_reliability": {
                        "score": conf_val,
                        "level": conf_level,
                        "message": conf_msg
                    }
                },
                "chart_data": chart_data 
            })

        except Exception as e:
            return Response({"error": f"Lỗi hệ thống: {str(e)}"}, status=500)

    def generate_reason(self, option, is_hot):
        rate = option['fill_rate']
        if rate >= 80: return "OPTIMAL_FILL"
        elif rate >= 60: return "BALANCED"
        elif is_hot: return "PROFIT_MAX"
        else: return "SAFE_OPTION"
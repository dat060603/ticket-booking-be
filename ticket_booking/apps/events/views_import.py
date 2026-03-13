import pandas as pd
import traceback # Quan trọng
import sys
from django.db import transaction
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework import status
from rest_framework import serializers
from .models import Match, Team, Stadium, League

class MatchScheduleImportSerializer(serializers.Serializer):
    league_id = serializers.IntegerField()
    file = serializers.FileField()

class ImportMatchScheduleView(APIView):
    parser_classes = [MultiPartParser, FormParser]
    serializer_class = MatchScheduleImportSerializer

    def post(self, request):
        try:
            # 1. KIỂM TRA INPUT
            file_obj = request.FILES.get('file')
            league_id = request.data.get('league_id')

            if not file_obj:
                return Response({"error": "Chưa chọn file Excel"}, status=400)
            if not league_id:
                return Response({"error": "Chưa chọn giải đấu"}, status=400)

            # 2. LOAD GIẢI ĐẤU
            try:
                league = League.objects.get(pk=league_id)
            except Exception as e:
                return Response({"error": f"Không tìm thấy giải đấu ID={league_id}"}, status=404)

            # 3. ĐỌC EXCEL (Bỏ try-except ở đây để lỗi bắn ra ngoài xem cho rõ)
            # Lưu ý: Cần cài đặt openpyxl: pip install openpyxl
            df = pd.read_excel(file_obj, engine='openpyxl') 
            df = df.fillna('') 

            valid_matches = []
            errors = []
            league_sport = league.sport 

            # 4. DUYỆT DATA
            for index, row in df.iterrows():
                line_num = index + 2
                row_error = []

                # Lấy dữ liệu an toàn
                round_val = str(row.get('Round', '')).strip()
                home_name = str(row.get('HomeTeam', '')).strip()
                away_name = str(row.get('AwayTeam', '')).strip()
                stadium_name = str(row.get('Stadium', '')).strip()
                date_val = row.get('Date')
                
                # Check rỗng
                if not round_val: row_error.append("Thiếu Vòng")
                if not home_name: row_error.append("Thiếu Chủ nhà")
                if not away_name: row_error.append("Thiếu Khách")
                
                # Check DB
                home_team = Team.objects.filter(team_name__iexact=home_name, sport=league_sport).first()
                if not home_team: row_error.append(f"Không tìm thấy đội '{home_name}'")

                away_team = Team.objects.filter(team_name__iexact=away_name, sport=league_sport).first()
                if not away_team: row_error.append(f"Không tìm thấy đội '{away_name}'")

                stadium = Stadium.objects.filter(stadium_name__iexact=stadium_name).first()
                if not stadium: row_error.append(f"Không tìm thấy sân '{stadium_name}'")

                # Check Date
                match_time = None
                if date_val:
                    try:
                        match_time = pd.to_datetime(date_val)
                    except:
                        row_error.append("Ngày giờ sai định dạng")
                
                if row_error:
                    errors.append(f"Dòng {line_num}: {', '.join(row_error)}")
                else:
                    valid_matches.append({
                        "match_time": match_time,
                        "description": str(row.get('Description', '')),
                        "round": round_val,
                        "league": league,
                        "stadium": stadium,
                        "team_1": home_team,
                        "team_2": away_team
                    })

            if errors:
                return Response({"status": "failed", "errors": errors}, status=400)

            # 5. LƯU DB
            with transaction.atomic():
                for item in valid_matches:
                    Match.objects.create(**item)

            return Response({"status": "success", "message": "Import thành công!"}, status=201)

        except Exception as e:
            # --- BẮT LỖI VÀ TRẢ VỀ JSON ---
            error_msg = str(e)
            trace_full = traceback.format_exc()
            print("!!!!!!! LỖI IMPORT !!!!!!!")
            print(trace_full) # In ra terminal lần nữa cho chắc
            
            # Trả về chi tiết lỗi cho Frontend hiển thị
            return Response({
                "error": "Lỗi xử lý phía Server (500)",
                "detail": error_msg,
                "traceback": trace_full
            }, status=500)
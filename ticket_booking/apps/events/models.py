# from django.db import models

# from apps.accounts.models import Employee

# class Team(models.Model):
#     team_id = models.AutoField(primary_key=True)
#     team_name = models.CharField(max_length=255, unique=True)
#     logo = models.ImageField(upload_to='team_logos/', null=True, blank=True, default='team_logos/default.webp')
#     head_coach = models.CharField(max_length=255)
#     description = models.TextField()

#     class Meta:
#         db_table = 'team'

#     def __str__(self):
#         return self.team_name

# class Stadium(models.Model):
#     stadium_id = models.AutoField(primary_key=True)
#     stadium_name = models.CharField(max_length=255, unique=True)
#     stadium_code = models.CharField(max_length=5, unique=True)
#     location = models.CharField(max_length=255)
#     capacity = models.IntegerField(null=True, blank=True)
#     stadium_layouts = models.ImageField(upload_to='stadium_layouts/', null=True, blank=True, default='stadium_layouts/stadium-1.png') 

#     class Meta:
#         db_table = 'stadium'

#     def __str__(self):
#         return self.stadium_name


# class League(models.Model):
#     league_id = models.AutoField(primary_key=True)
#     league_name = models.CharField(max_length=255)
#     league_type = models.IntegerField(default=0)  
#     start_date = models.DateField()
#     end_date = models.DateField()
#     created_at = models.DateTimeField(auto_now_add=True)
#     updated_at = models.DateTimeField(auto_now=True)

#     class Meta:
#         db_table = 'league'

#     def __str__(self):
#         return self.league_name


# class Match(models.Model):
#     match_id = models.AutoField(primary_key=True)
#     match_time = models.DateTimeField()
#     description = models.TextField()
#     stadium = models.ForeignKey(Stadium, on_delete=models.CASCADE)
#     league = models.ForeignKey(League, on_delete=models.CASCADE)
#     round = models.CharField(max_length=100)
#     team_1 = models.ForeignKey(Team, related_name='home_matches', on_delete=models.CASCADE)
#     team_2 = models.ForeignKey(Team, related_name='away_matches', on_delete=models.CASCADE)
#     created_at = models.DateTimeField(auto_now_add=True)

#     class Meta:
#         db_table = 'match'
#         constraints = [
#             models.UniqueConstraint(fields=['match_time', 'stadium'], name='unique_match_time_stadium'),
#             models.UniqueConstraint(fields=['league', 'round', 'team_1', 'team_2'], name='unique_league_round_teams'),
#         ]
    
#     def __str__(self):
#         return f'{self.team_1} vs {self.team_2}'


# class MatchHistory(models.Model):
#     CHANGE_TYPE_CHOICES = [
#         ('update', 'Cập nhật thông tin'),
#         ('postpone', 'Hoãn'),
#         ('cancel', 'Hủy'),
#         ('reschedule', 'Dời lịch thi đấu'),
#     ]

#     m_history_id = models.AutoField(primary_key=True)
#     match = models.ForeignKey(Match, on_delete=models.CASCADE)
#     changed_at = models.DateTimeField(auto_now_add=True)
#     employee = models.ForeignKey(Employee, on_delete=models.CASCADE)
#     change_type = models.CharField(max_length=50, choices=CHANGE_TYPE_CHOICES)
#     old_value = models.JSONField()
#     new_value = models.JSONField()
#     reason = models.TextField()

#     class Meta:
#         db_table = 'match_history'

#     def __str__(self):
#         return f'History of {self.match}'
from django.db import models
from django.core.exceptions import ValidationError
from apps.accounts.models import Employee # Giả định bạn import Employee từ đây

# --- MỚI: Model Sport (Định nghĩa môn thể thao) ---
# Model này là "mẹ" của Team, League, và Match
class Sport(models.Model):
    sport_id = models.AutoField(primary_key=True)
    sport_name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)

    class Meta:
        db_table = 'sport'

    def __str__(self):
        return self.sport_name


# --- CẬP NHẬT: Model Team (Thêm 'sport' và 'constraints') ---
class Team(models.Model):
    team_id = models.AutoField(primary_key=True)
    
    # Liên kết với Sport
    sport = models.ForeignKey(Sport, on_delete=models.CASCADE)
    
    team_name = models.CharField(max_length=255) # Bỏ unique=True ở đây
    logo = models.ImageField(upload_to='team_logos/', null=True, blank=True, default='team_logos/default.webp')
    head_coach = models.CharField(max_length=255)
    description = models.TextField()
    rating = models.IntegerField(default=5, verbose_name="Chỉ số sức hút")
    class Meta:
        db_table = 'team'
        # Ràng buộc mới: Tên đội là duy nhất TRONG MÔN THỂ THAO đó
        constraints = [
            models.UniqueConstraint(fields=['sport', 'team_name'], name='unique_team_name_per_sport')
        ]

    def __str__(self):
        # Hiển thị rõ đội này thuộc môn thể thao nào
        return f'{self.team_name} ({self.sport.sport_name})'


# --- KHÔNG ĐỔI: Model Stadium (Đã đủ linh hoạt) ---
# Model này dùng chung cho cả Sân vận động và Nhà thi đấu
class Stadium(models.Model):
    stadium_id = models.AutoField(primary_key=True)
    stadium_name = models.CharField(max_length=255, unique=True)
    stadium_code = models.CharField(max_length=5, unique=True)
    location = models.CharField(max_length=255)
    capacity = models.IntegerField(null=True, blank=True)
    stadium_layouts = models.ImageField(upload_to='stadium_layouts/', null=True, blank=True, default='stadium_layouts/stadium-1.png') 

    class Meta:
        db_table = 'stadium'

    def __str__(self):
        return self.stadium_name


# --- CẬP NHẬT: Model League (Thêm 'sport' và 'league_type') ---
class League(models.Model):
    
    # Định nghĩa các thể thức thi đấu (áp dụng chung cho mọi môn)
    class LeagueFormat(models.TextChoices):
        ROUND_ROBIN = 'round_robin', 'Đấu vòng tròn (V. League, Ngoại Hạng Anh)'
        KNOCKOUT = 'knockout', 'Đấu loại trực tiếp (Cúp Quốc gia)'
        HYBRID = 'hybrid', 'Hỗn hợp (World Cup, C1, NBA Playoffs)'
        FRIENDLY = 'friendly', 'Giao hữu'
        OTHER = 'other', 'Khác'

    league_id = models.AutoField(primary_key=True)
    
    # Liên kết với Sport
    sport = models.ForeignKey(Sport, on_delete=models.CASCADE)
    
    league_name = models.CharField(max_length=255)
    
    # Cập nhật league_type
    league_type = models.CharField(
        max_length=20,
        choices=LeagueFormat.choices,
        default=LeagueFormat.ROUND_ROBIN,
        verbose_name="Thể thức thi đấu"
    )
    
    start_date = models.DateField()
    end_date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'league'

    def __str__(self):
        # Hiển thị rõ giải đấu này thuộc thể thức nào
        return f'{self.league_name} ({self.get_league_type_display()})'


# --- CẬP NHẬT: Model Match (Thêm logic validation 'clean') ---
class Match(models.Model):
    match_id = models.AutoField(primary_key=True)
    match_time = models.DateTimeField()
    description = models.TextField(null=True, blank=True)
    stadium = models.ForeignKey(Stadium, on_delete=models.CASCADE)
    league = models.ForeignKey(League, on_delete=models.CASCADE)
    round = models.CharField(max_length=100) # Giữ CharField là linh hoạt nhất
    team_1 = models.ForeignKey(Team, related_name='home_matches', on_delete=models.CASCADE)
    team_2 = models.ForeignKey(Team, related_name='away_matches', on_delete=models.CASCADE)
    is_hot_match = models.BooleanField(default=False, verbose_name="Trận cầu tâm điểm")
    importance = models.IntegerField(default=3, verbose_name="Mức độ quan trọng (1-5)")
    created_at = models.DateTimeField(auto_now_add=True)

    # Thêm logic validation để đảm bảo tính toàn vẹn dữ liệu
    def clean(self):
        super().clean()
        
        # 1. Đảm bảo các đội và giải đấu thuộc cùng một môn thể thao
        if self.league_id and self.team_1_id:
            if self.league.sport != self.team_1.sport:
                raise ValidationError(f'Lỗi: Giải đấu "{self.league}" là ({self.league.sport.sport_name}) '
                                      f'nhưng Đội 1 "{self.team_1}" lại là ({self.team_1.sport.sport_name}).')
        
        if self.league_id and self.team_2_id:
            if self.league.sport != self.team_2.sport:
                raise ValidationError(f'Lỗi: Giải đấu "{self.league}" là ({self.league.sport.sport_name}) '
                                      f'nhưng Đội 2 "{self.team_2}" lại là ({self.team_2.sport.sport_name}).')
        
        # 2. Đảm bảo hai đội không phải là một
        if self.team_1_id and self.team_1_id == self.team_2_id:
            raise ValidationError('Lỗi: Đội 1 và Đội 2 không thể giống nhau.')

    class Meta:
        db_table = 'match'
        constraints = [
            models.UniqueConstraint(fields=['match_time', 'stadium'], name='unique_match_time_stadium'),
            models.UniqueConstraint(fields=['league', 'round', 'team_1', 'team_2'], name='unique_league_round_teams'),
        ]
    
    def __str__(self):
        return f'{self.team_1} vs {self.team_2}'
    # Mặc định là trận thường, không cần nhập
    is_hot_match = models.BooleanField(default=False, verbose_name="Trận cầu tâm điểm")
    importance = models.IntegerField(default=3, verbose_name="Mức độ quan trọng (1-5)")

    # --- PHẦN QUAN TRỌNG: TỰ ĐỘNG TÍNH TOÁN ---
    def save(self, *args, **kwargs):
        # Chỉ tự động tính nếu Admin chưa set thủ công (hoặc khi tạo mới)
        if self.pk is None or (self.importance == 3 and not self.is_hot_match):
            self.calculate_hotness()
        super().save(*args, **kwargs)

    def calculate_hotness(self):
        # 1. Logic cơ bản dựa trên Rating (Tính nền tảng trước)
        if not self.team_1 or not self.team_2:
            return

        r1 = self.team_1.rating
        r2 = self.team_2.rating
        total = r1 + r2
        diff = abs(r1 - r2)
        
        # --- BƯỚC 1: TÍNH TOÁN DỰA TRÊN CHUYÊN MÔN (RATING) ---
        if total >= 17:
            self.is_hot_match = True
            self.importance = 5
        elif total >= 15:
            self.is_hot_match = False
            self.importance = 4
        elif diff >= 5: # Chênh lệch quá lớn
            self.is_hot_match = False
            self.importance = 4 if max(r1, r2) >= 9 else (3 if max(r1, r2) >= 7 else 2)
        elif total <= 8:
            self.is_hot_match = False
            self.importance = 1
        else:
            self.is_hot_match = False
            self.importance = 3

        # --- BƯỚC 2: LOGIC "TỪ KHÓA ĐẶC BIỆT" (OVERRIDE) ---
        # Đây là cách giải quyết Derby mà không cần sửa Model Team
        # Nếu mô tả trận đấu chứa các từ khóa nhạy cảm -> Tự động kích hoạt HOT
        
        if self.description:
            desc_lower = self.description.lower()
            
            # Danh sách từ khóa báo hiệu trận HOT (Hỗ trợ nhiều môn, nhiều ngôn ngữ)
            HOT_KEYWORDS = [
                'derby',          # Bóng đá
                'chung kết', 'final', # Trận quan trọng
                'bán kết', 'semi-final',
                'siêu kinh điển', 'el clasico', 
                'đại chiến', 'big match',
                'kình địch', 'rivalry',
                'all-star',       # Bóng rổ
                'playoff', 'play-off'
            ]

            # Nếu tìm thấy bất kỳ từ khóa nào trong mô tả
            if any(keyword in desc_lower for keyword in HOT_KEYWORDS):
                self.is_hot_match = True
                # Đã là Derby/Chung kết thì Importance ít nhất phải là 4
                if self.importance < 4:
                    self.importance = 4
                
                # Nếu vốn dĩ rating cao (4) thì đẩy lên max (5)
                if self.importance == 4:
                    self.importance = 5
    

# --- KHÔNG ĐỔI: Model MatchHistory (Đã đủ linh hoạt) ---
class MatchHistory(models.Model):
    CHANGE_TYPE_CHOICES = [
        ('update', 'Cập nhật thông tin'),
        ('postpone', 'Hoãn'),
        ('cancel', 'Hủy'),
        ('reschedule', 'Dời lịch thi đấu'),
    ]

    m_history_id = models.AutoField(primary_key=True)
    match = models.ForeignKey(Match, on_delete=models.CASCADE)
    changed_at = models.DateTimeField(auto_now_add=True)
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE)
    change_type = models.CharField(max_length=50, choices=CHANGE_TYPE_CHOICES)
    old_value = models.JSONField()
    new_value = models.JSONField()
    reason = models.TextField()

    class Meta:
        db_table = 'match_history'

    def __str__(self):
        return f'History of {self.match}'
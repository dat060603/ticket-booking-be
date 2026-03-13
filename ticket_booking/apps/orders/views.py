from rest_framework import generics
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from apps.events.models import Match
from django.db.models import Q, Sum
from django.conf import settings
from django.utils import timezone
from datetime import datetime, timedelta
from django.core.mail import send_mail
from django.core.mail import EmailMessage
from django.conf import settings
from io import BytesIO
from base64 import b64decode

from .utils import check_payment_expiration
from .serializers import *
from apps.returns.models import TicketReturn

import redis
import time
import qrcode
import base64
from io import BytesIO

class MatchListAPIView(generics.ListAPIView):
    serializer_class = MatchSerializer

    def get_queryset(self):
        # Filter matches that have at least one valid section price
        queryset = Match.objects.filter(
            Q(tickets__is_closed=False) &
            Q(tickets__available_seats__gt=0)  # available_tickets > 0
        ).distinct()

        return queryset

class MatchDetailAPIView(generics.RetrieveAPIView):
    serializer_class = MatchSerializer
    lookup_field = 'match_id'

    def get_queryset(self):
        # Lọc các trận đấu có ít nhất một section không đóng và có vé còn lại
        queryset = Match.objects.filter(
            Q(tickets__is_closed=False) &
            Q(tickets__available_seats__gt=0)  # available_tickets > 0
        ).distinct()
        return queryset

    def get(self, request, *args, **kwargs):
        # Lấy queryset đã lọc
        queryset = self.get_queryset()

        # Tìm kiếm trận đấu theo match_id
        match_id = self.kwargs.get('match_id')
        match = queryset.filter(match_id=match_id).first()

        # Nếu không tìm thấy trận đấu hoặc không có section mở, trả về lỗi 400
        if not match:
            return Response(
                {"detail": "Match not found or no open sections available"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Trả về dữ liệu của trận đấu đã tìm thấy
        serializer = self.get_serializer(match)
        return Response(serializer.data)
    

class PromotionListView(APIView):
    def get(self, request, match_id, section_id):
        # Get current time
        now = timezone.now()

        # Lọc các PromotionDetail theo match_id và section_id
        promotion_details = PromotionDetail.objects.filter(match_id=match_id, section_id=section_id)
        
        # Lọc các promotion nằm trong khoảng start_time - end_time và usage_limit > 0
        promotions = Promotion.objects.filter(
            promo_id__in=promotion_details.values('promo'),
            start_time__lte=now,        # Check if the promotion start_time is before or equal to the current time
            end_time__gte=now,          # Check if the promotion end_time is after or equal to the current time
            usage_limit__gt=0           # Ensure the usage limit is greater than 0
        )

        # Serialize dữ liệu và trả về phản hồi
        serializer = PromotionSerializer(promotions, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


# Order
class OrderCreateAPIView(generics.CreateAPIView):
    serializer_class = OrderSerializer

    def create(self, request, *args, **kwargs):
        print("=" * 50)
        print("Raw request data:", request.data)
        print("=" * 50)

        try:
            data = request.data.copy()
            
            # ⭐ Tính total_amount từ order_details nếu client không gửi chính xác
            if isinstance(data.get('order_details'), list):
                total_amount = 0
                for od in data['order_details']:
                    try:
                        price = float(od.get('price', 0))
                        total_amount += price
                    except (ValueError, TypeError):
                        pass
                data['total_amount'] = round(total_amount, 2)
                
                # Pop các trường không cần
                for od in data['order_details']:
                    od.pop('price', None)
                    od.pop('qr_code', None)
                    od.pop('seat_id', None)

            print("Sanitized payload:", data)

            serializer = self.get_serializer(data=data)
            if serializer.is_valid():
                order = serializer.save()
                return Response({
                    "status": "success",
                    "message": "Đơn hàng được đặt thành công.",
                    "data": OrderSerializer(order).data
                }, status=status.HTTP_201_CREATED)

            print("Errors:", serializer.errors)
            return Response({
                "status": "error",
                "message": "Lỗi khi thực hiện mua vé.",
                "errors": serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)

        except Exception as e:
            import traceback
            print("EXCEPTION:", traceback.format_exc())
            return Response({
                "status": "error",
                "message": f"Lỗi server: {str(e)}",
                "errors": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
redis_client = redis.StrictRedis.from_url(settings.REDIS_URL, decode_responses=True)

class PaymentCreateView(APIView):
    def post(self, request, *args, **kwargs):
        # Lấy order_id từ yêu cầu (có thể được gửi qua URL hoặc body request)
        order_id = request.data.get('order_id')
        # print(order_id)
        payment_method = request.data.get('payment_method', 'bank_card')  # Mặc định là 'bank_card'
        
        # Kiểm tra xem order_id có hợp lệ không
        try:
            order = Order.objects.get(order_id=order_id)
            print(order)
        except Order.DoesNotExist:
            return Response({"error": "Order not found."}, status=status.HTTP_400_BAD_REQUEST)
        
        # Tạo Payment
        payment_data = {
            'order': order.order_id,
            'payment_method': payment_method,
            'payment_status': 'pending',
            'transaction_code': f'TX-{order.order_id}-{int(time.time())}'  # Tạo transaction code duy nhất
        }
        
        payment_serializer = PaymentSerializer(data=payment_data)
        if payment_serializer.is_valid():
            payment = payment_serializer.save()

            # Lưu trạng thái thanh toán vào Redis (TTL 10 phút)
            redis_key = f"payment_hold:{payment.payment_id}"
            redis_client.set(redis_key, 'pending', ex=600)  # 'ex=600' set TTL 10 phút

            # Tạo mã QR chứa transaction_code
            qr_data = f"Thanh toán cho đơn hàng {order.order_id}\nMã giao dịch: {payment.transaction_code}"
            qr_img = self.create_qr_code(qr_data)

            # Trả về mã QR dưới dạng hình ảnh
            return Response({
                "payment": payment_serializer.data,
                "qr_code": qr_img
            }, status=status.HTTP_201_CREATED)
        else:
            return Response(payment_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def create_qr_code(self, data):
        """
        Tạo mã QR từ dữ liệu và trả về mã QR dưới dạng hình ảnh (base64)
        """
        # Sử dụng thư viện qrcode để tạo mã QR
        qr = qrcode.QRCode(
            version=1,  # Kích thước của mã QR
            error_correction=qrcode.constants.ERROR_CORRECT_L,  # Độ chính xác khi mã QR bị hỏng
            box_size=10,  # Kích thước ô của mã QR
            border=4,  # Độ dày của biên giới
        )
        qr.add_data(data)
        qr.make(fit=True)

        # Tạo hình ảnh từ mã QR
        img = qr.make_image(fill='black', back_color='white')

        # Lưu hình ảnh vào bộ nhớ dưới dạng BytesIO (giúp trả về ảnh mà không cần lưu file)
        img_io = BytesIO()
        img.save(img_io, 'PNG')
        img_io.seek(0)

        # Chuyển đổi hình ảnh thành dữ liệu base64 để gửi qua API (nếu cần)
        from base64 import b64encode
        qr_img_base64 = b64encode(img_io.getvalue()).decode('utf-8')

        return qr_img_base64
        

class PaymentStatusCheckView(APIView):
    def post(self, request, *args, **kwargs):
        payment_id = request.data.get('payment_id')
        
        # Kiểm tra payment_id hợp lệ
        try:
            payment = Payment.objects.get(payment_id=payment_id)
        except Payment.DoesNotExist:
            return Response({"error": "Payment not found."}, status=status.HTTP_400_BAD_REQUEST)

        # Kiểm tra trạng thái thanh toán trong Redis
        redis_key = f"payment_hold:{payment_id}"
        payment_status = redis_client.get(redis_key)

        if payment_status == 'pending':
            # Thanh toán thành công, cập nhật trạng thái
            payment.payment_status = 'success'
            payment.save()

            # Xóa thông tin trong Redis
            redis_client.delete(redis_key)

            return Response({"message": "Payment successful."}, status=status.HTTP_200_OK)
        else:
            # Nếu thanh toán đã hết thời gian hoặc không còn trong Redis
            return Response({"error": "Payment has expired or already processed."}, status=status.HTTP_400_BAD_REQUEST)



import json
import uuid
import hmac
import hashlib
import requests


class MoMoPaymentAPIView(APIView):

    def post(self, request):
        # Extract order ID and other details from the request

        order_id = request.data.get('order')
        amount = request.data.get('amount', 50000)  # You can adjust this
        order_info = request.data.get('order_info', 'Pay with MoMo')
        CURRENT_DOMAIN = "https://willene-spiriferous-drucilla.ngrok-free.dev"
        ipn_url = f"{CURRENT_DOMAIN}/api/orders/done-payment/"        # Trỏ về đúng cái view vừa tạo ở bước 1 và 2
        redirect_url = f"{CURRENT_DOMAIN}/api/orders/payment-result/"

         # Extract order ID and other details from the request

        # order_id = request.data.get('order')
        # amount = request.data.get('amount', 50000)  # You can adjust this
        # order_info = request.data.get('order_info', 'Pay with MoMo')
        # redirect_url = request.data.get('redirect_url', 'https://your-redirect-url.com')
        # ipn_url = request.data.get('ipn_url', 'https://your-ipn-url.com')
        
        # Prepare parameters for MoMo request
        access_key = "F8BBA842ECF85"
        secret_key = "K951B6PE1waDMi640xX08PD3vg6EkVlz"
        partner_code = "MOMO"
        request_type = "payWithMethod"

        order = Order.objects.get(order_id=order_id)

        # order_id = str(uuid.uuid4())
        request_id = str(uuid.uuid4())
        extra_data = ""  # Can encode in base64 if needed

        # Create raw signature
        raw_signature = f"accessKey={access_key}&amount={amount}&extraData={extra_data}&ipnUrl={ipn_url}&orderId={order_id}&orderInfo={order_info}&partnerCode={partner_code}&redirectUrl={redirect_url}&requestId={request_id}&requestType={request_type}"
        
        # Generate the signature
        h = hmac.new(secret_key.encode('utf-8'), raw_signature.encode('utf-8'), hashlib.sha256)

        signature = h.hexdigest()

        # Prepare data to send to MoMo
        data = {
            'partnerCode': partner_code,
            'orderId': order_id,
            'partnerName': 'MoMo Payment',
            'storeId': 'Test Store',
            'ipnUrl': ipn_url,
            'amount': str(amount),
            'lang': 'vi',
            'requestType': request_type,
            'redirectUrl': redirect_url,
            'autoCapture': True,
            'orderInfo': order_info,
            'requestId': request_id,
            'extraData': extra_data,
            'signature': signature,
            'orderGroupId': ''
        }

        # Send request to MoMo
        endpoint = "https://test-payment.momo.vn/v2/gateway/api/create"
        response = requests.post(endpoint, json=data)

        print(response.json())

        # If MoMo payment URL is returned successfully
        if response.status_code == 200:
            payment_data = response.json()

            expiration_time = timezone.now() + timedelta(minutes=5)

            # check_payment_expiration.delay()
            # Create a new Payment object in the database
            payment = Payment.objects.create(
                order=order,
                payment_method='transfer',
                payment_status='pending',
                transaction_code=payment_data.get('transactionCode'),
                expiration_time=expiration_time,
            )
            return Response(payment_data, status=status.HTTP_200_OK)
        
        return Response({"error": "Payment request failed"}, status=status.HTTP_400_BAD_REQUEST)

# Phần giả lậop thanh toán không momo
# import time
# from rest_framework.views import APIView
# from rest_framework.response import Response
# from rest_framework import status
# from django.utils import timezone
# from datetime import timedelta
# from .models import Order, Payment 

# class MoMoPaymentAPIView(APIView):
#     def post(self, request):
#         print("\n---------- ⚠️ CHẾ ĐỘ GIẢ LẬP THANH TOÁN (BYPASS MOMO) ----------")
        
#         # 1. Lấy dữ liệu từ Frontend gửi lên
#         order_id = request.data.get('order')
        
#         # Frontend đã gửi sẵn link trang đích (qrcode.html) trong biến này
#         # Code JS: redirect_url: window.location.origin + '/pages/customer/qrcode.html'
#         frontend_redirect_url = request.data.get('redirect_url') 
        
#         try:
#             # 2. XỬ LÝ DATABASE NGAY LẬP TỨC (Update thành công luôn)
#             order = Order.objects.get(order_id=order_id)
            
#             # 2.1. Tạo bản ghi Payment thành công
#             expiration_time = timezone.now() + timedelta(minutes=10)
#             fake_trans_id = f"MOCK_{int(time.time())}"
            
#             Payment.objects.create(
#                 order=order,
#                 payment_method='transfer',   # Hoặc 'momo'
#                 payment_status='success',    # <--- QUAN TRỌNG: success/completed
#                 transaction_code=fake_trans_id,
#                 expiration_time=expiration_time,
#             )

#             # 2.2. Cập nhật trạng thái đơn hàng
#             # Dựa vào code cũ (MoMoIPNAPIView), bạn dùng trạng thái 'received'
#             order.order_status = 'received' 
#             order.save()
            
#             print(f"✅ Đã giả lập thanh toán thành công cho đơn: {order_id}")

#             # 3. TẠO LINK GIẢ LẬP ĐỂ TRẢ VỀ FRONTEND
#             # Thay vì trả về link MoMo, ta trả về link trang qrcode.html kèm tham số thành công
#             # Frontend sẽ chạy dòng: window.location.href = mock_url -> Nhảy trang luôn
            
#             mock_url = f"{frontend_redirect_url}?resultCode=0&orderId={order_id}&message=GiaoDichThanhCong"

#             return Response({
#                 'payUrl': mock_url,  # Frontend chỉ cần biến này để redirect
#                 'message': 'Giả lập thanh toán thành công'
#             }, status=status.HTTP_200_OK)

#         except Order.DoesNotExist:
#             return Response({"error": "Order not found"}, status=status.HTTP_404_NOT_FOUND)
#         except Exception as e:
#             print("❌ Lỗi Server:", str(e))
#             return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)





class MoMoIPNAPIView(APIView):
    def post(self, request):
        # Lấy thông tin từ MoMo gửi về (MoMo gửi dưới dạng POST)
        data = request.data

        print(data)

        # Kiểm tra chữ ký để xác minh tính hợp lệ của thông báo từ MoMo
        access_key = "F8BBA842ECF85"
        secret_key = "K951B6PE1waDMi640xX08PD3vg6EkVlz"
        partner_code = "MOMO"

        # Tạo raw_signature từ các tham số nhận được
        # raw_signature = f"accessKey={access_key}&amount={data['amount']}&orderId={data['orderId']}&partnerCode={partner_code}&paymentStatus={data['resultCode']}&transactionId={data['transId']}&requestId={data['requestId']}"
        raw_signature = (
            f"accessKey={access_key}"
            f"&amount={data['amount']}"
            f"&extraData={data['extraData']}"
            f"&message={data['message']}"
            f"&orderId={data['orderId']}"
            f"&orderInfo={data['orderInfo']}"
            f"&orderType={data['orderType']}"
            f"&partnerCode={partner_code}"
            f"&payType={data['payType']}"
            f"&requestId={data['requestId']}"
            f"&responseTime={data['responseTime']}"
            f"&resultCode={data['resultCode']}"
            f"&transId={data['transId']}"
        )
        # Tạo chữ ký từ raw_signature
        h = hmac.new(secret_key.encode('utf-8'), raw_signature.encode('utf-8'), hashlib.sha256)
        signature = h.hexdigest()

        # Kiểm tra chữ ký có khớp với chữ ký gửi về từ MoMo hay không
        # if signature != data['signature']:
        #     return Response({"error": "Invalid signature"}, status=status.HTTP_400_BAD_REQUEST)
        order = Order.objects.get(order_id=data['orderId'])
        payment = Payment.objects.get(order=order)

        # Kiểm tra trạng thái thanh toán
        if data['resultCode'] == 0:  # 0 là thành công
            # Cập nhật trạng thái thanh toán thành công
            try:
                payment.payment_status = 'success'
                payment.transaction_code = data['transId']
                if data['payType'] == 'qr':
                    payment.payment_method = 'transfer'
                else:
                    payment.payment_method = 'bank_card'
                payment.created_at = timezone.now()
                payment.save()

                payment.order.order_status = 'received'
                payment.order.save()


                # Trả về thông báo thành công
                return Response({"message": "Payment successful"}, status=status.HTTP_200_OK)
            except Payment.DoesNotExist:
                return Response({"error": "Payment not found"}, status=status.HTTP_400_BAD_REQUEST)
        else:
            payment.payment_status = 'failed'
            payment.save()       # (Có thể bỏ nếu không cần log lại trạng thái)
            payment.delete()
            return Response({"error": "Payment failed"}, status=status.HTTP_400_BAD_REQUEST)
        

def create_qr_code(data):
        """
        Tạo mã QR từ dữ liệu và trả về mã QR dưới dạng hình ảnh (base64)
        """
        # Sử dụng thư viện qrcode để tạo mã QR
        qr = qrcode.QRCode(
            version=1,  # Kích thước của mã QR
            error_correction=qrcode.constants.ERROR_CORRECT_L,  # Độ chính xác khi mã QR bị hỏng
            box_size=10,  # Kích thước ô của mã QR
            border=4,  # Độ dày của biên giới
        )
        qr.add_data(data)
        qr.make(fit=True)

        # Tạo hình ảnh từ mã QR
        img = qr.make_image(fill='black', back_color='white')

        # Lưu hình ảnh vào bộ nhớ dưới dạng BytesIO (giúp trả về ảnh mà không cần lưu file)
        img_io = BytesIO()
        img.save(img_io, 'PNG')
        img_io.seek(0)

        # Chuyển đổi hình ảnh thành dữ liệu base64 để gửi qua API (nếu cần)
        from base64 import b64encode
        qr_img_base64 = b64encode(img_io.getvalue()).decode('utf-8')

        return qr_img_base64


class OrderDetailQRAPIView(APIView):
    def post(self, request, *args, **kwargs):
        # Lấy order_id từ body của request
        order_id = request.data.get('order_id')

        if not order_id:
            return Response(
                {"error": "order_id is required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            # Lấy Order từ Order ID
            order = Order.objects.get(order_id=order_id)
        except Order.DoesNotExist:
            return Response(
                {"error": "Order not found."},
                status=status.HTTP_404_NOT_FOUND
            )

        # Lấy tất cả các OrderDetail liên quan đến Order này
        order_details = OrderDetail.objects.filter(order=order)

        if not order_details:
            return Response(
                {"error": "No order details found for this order."},
                status=status.HTTP_404_NOT_FOUND
            )

        # Tạo danh sách chứa các thông tin order_detail và mã QR tương ứng
        order_details_with_qr = []
        match_info = {}

        for order_detail in order_details:
            # Tạo QR Code cho mỗi OrderDetail
            qr_code_data = f"Order ID: {order.order_id}, Seat: {order_detail.seat.seat_number}, Price: {order_detail.price}"
            qr_code = create_qr_code(qr_code_data)  # Gọi hàm tạo QR từ dữ liệu

            order_detail.qr_code = qr_code
            order_detail.save()

            match = order_detail.pricing.match
            match_info = {
                "match_id": match.match_id,
                "match_time": match.match_time,
                "league": match.league.league_name,
                "team_1": match.team_1.team_name,
                "team_2": match.team_2.team_name
            }

            # Lấy thông tin khuyến mãi liên quan đến OrderDetail
            promotion_info = {}
            if order_detail.promotion:
                promotion = order_detail.promotion
                promotion_info = {
                    "promo_code": promotion.promo_code,
                    "discount_type": promotion.discount_type,
                    "discount_value": promotion.discount_value
                }

            # Thêm thông tin của OrderDetail, QR Code và Promotion vào danh sách
            order_details_with_qr.append({
                "detail_id": order_detail.detail_id,
                "pricing_id": order_detail.pricing.pricing_id,
                "pricing_section": order_detail.pricing.section.section_name,
                "seat": order_detail.seat.seat_number if order_detail.seat else None,
                "price": str(order_detail.price),  # Chuyển đổi thành chuỗi để gửi qua API
                "qr_code": qr_code,
                **promotion_info  # Thêm thông tin khuyến mãi vào response
            })

        try:
            payment = Payment.objects.get(order=order)
        except Payment.DoesNotExist:
            payment_info = {
                "payment_method": "N/A",
                "transaction_code": "N/A",
                "payment_status": "N/A"
            }
        else:
            payment_info = {
                "payment_method": payment.payment_method,
                "transaction_code": payment.transaction_code,
                "payment_status": payment.payment_status
            }

            if payment.payment_status == 'success' and order.user.email:
                self.send_invoice_email(order, payment)

        # Trả về thông tin của đơn hàng cùng với mã QR và thông tin khuyến mãi cho mỗi OrderDetail
        return Response({
            "order_id": order.order_id,
            "user": order.user.full_name if order.user else "Guest",
            "total_amount": str(order.total_amount),
            "order_status": order.order_status,
            "order_details": order_details_with_qr,
            **payment_info,
            "match": match_info
        }, status=status.HTTP_200_OK)

    def send_invoice_email(self, order, payment):
        subject = f"Hóa đơn thanh toán cho đơn hàng {order.order_id}"
        message = f"""
        Chào {order.user.full_name if order.user else 'Khách hàng'},
        
        Cảm ơn bạn đã mua vé tại hệ thống chúng tôi. Dưới đây là thông tin đơn hàng của bạn:

        - Mã đơn hàng: {order.order_id}
        - Tổng tiền: {order.total_amount} VND
        - Trạng thái thanh toán: {payment.payment_status}
        - Phương thức thanh toán: {payment.payment_method}
        - Mã giao dịch: {payment.transaction_code}

        Chi tiết vé:
        {self.get_order_details_string(order)}

        Chúng tôi mong muốn được phục vụ bạn trong những lần sau!

        Trân trọng,
        Hệ thống bán vé trực tuyến
        """
        
        # Tạo các hình ảnh mã QR từ base64 cho mỗi OrderDetail
        qr_code_images = []
        for order_detail in order.order_details.all():
            qr_code_image = self.create_qr_code_image_from_base64(order_detail)
            qr_code_images.append(qr_code_image)

        # Tạo email và đính kèm tất cả các mã QR
        email = EmailMessage(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [order.user.email],
        )

        # Đính kèm các QR code vào email
        for i, qr_code_image in enumerate(qr_code_images, start=1):
            email.attach(f'qr_code_{i}.png', qr_code_image, 'image/png')

        email.send(fail_silently=False)

    def create_qr_code_image_from_base64(self, order_detail):
        """
        Chuyển đổi base64 QR code thành hình ảnh và trả về dưới dạng nhị phân.
        """
        # Lấy base64 QR code của OrderDetail
        qr_code_base64 = order_detail.qr_code  # Lấy mã QR từ OrderDetail
        img_data = b64decode(qr_code_base64)

        # Tạo hình ảnh từ dữ liệu base64
        img_io = BytesIO(img_data)
        
        return img_io.getvalue()

    def get_order_details_string(self, order):
        details = []
        for order_detail in order.order_details.all():
            promotion_info = ''
            if order_detail.promotion:
                promotion = order_detail.promotion
                promotion_info = f" - Mã khuyến mãi: {promotion.promo_code}, Loại giảm giá: {promotion.discount_type}, Giá trị giảm: {promotion.discount_value} VND"

            details.append(f"- Ghế: {order_detail.seat.seat_number if order_detail.seat else 'Chưa chọn'}, Giá: {order_detail.price} VND{promotion_info}")
        return "\n".join(details)
    

class OrderListView(APIView):
    def get(self, request):
        # Lấy customer_id từ tham số query string
        customer_id = request.query_params.get('customer_id')

        if not customer_id:
            return Response({
                "status": "error",
                "message": "customer_id là bắt buộc.",
                "data": None
            }, status=status.HTTP_400_BAD_REQUEST)

        # Lọc các đơn hàng có trạng thái 'received' và thuộc về customer_id
        # Chỉ lấy các đơn hàng trước thời gian diễn ra trận đấu
        orders = Order.objects.filter(
            order_status='received',
            user_id=customer_id,
            order_details__pricing__match__match_time__gt=timezone.now()
        ).distinct()

        if not orders.exists():
            return Response({
                "status": "error",
                "message": "Không tìm thấy đơn hàng nào cho khách hàng này.",
                "data": None
            }, status=status.HTTP_404_NOT_FOUND)

        data = []

        for order in orders:
            order_details_data = []
            match, stadium_name = None, None

            for order_detail in order.order_details.all():
                # Lấy return data nếu có
                try:
                    ticket_return = TicketReturn.objects.get(detail=order_detail)
                    return_data = {
                        "return_id": ticket_return.return_id,
                        "return_reason": ticket_return.return_reason,
                        "return_status": ticket_return.return_status,
                        "refund_method": ticket_return.refund_method,
                        "return_time": ticket_return.return_time,
                        "processed_time": ticket_return.processed_time,
                        "refund_amount": str(ticket_return.refund_amount) if ticket_return.refund_amount else None,
                        "employee": ticket_return.employee.full_name if ticket_return.employee else None,
                        "note": ticket_return.note,
                    }
                except TicketReturn.DoesNotExist:
                    return_data = None

                section_name = order_detail.pricing.section.section_name if order_detail.pricing.section else None
                match = order_detail.pricing.match if order_detail.pricing.match else None
                stadium_name = match.stadium.stadium_name if match and match.stadium else None

                order_details_data.append({
                    "detail_id": order_detail.detail_id,
                    "pricing": order_detail.pricing.pricing_id,
                    "price": str(order_detail.price),
                    "promotion": order_detail.promotion.promo_code if order_detail.promotion else None,
                    "seat": order_detail.seat.seat_number if order_detail.seat else None,
                    "updated_at": order_detail.updated_at,
                    "section_name": section_name,
                    "return": return_data
                })

            match_data = {
                "match_id": match.match_id if match else None,
                "match_time": match.match_time if match else None,
                "league": match.league.league_name if match and match.league else None,
                "team_1": match.team_1.team_name if match and match.team_1 else None,
                "team_2": match.team_2.team_name if match and match.team_2 else None,
            }

            data.append({
                "order_id": order.order_id,
                "user": order.user.id if order.user else None,
                "total_amount": str(order.total_amount),
                "order_status": order.order_status,
                "order_method": order.order_method,
                "created_at": order.created_at,
                "order_details": order_details_data,
                "match": match_data,
                "stadium_name": stadium_name,
            })

        return Response({
            "status": "success",
            "message": "Danh sách đơn hàng đã được lấy thành công.",
            "data": data
        }, status=status.HTTP_200_OK)
    

class TicketReturnAPIView(APIView):
    def post(self, request):
        # Lấy detail_id và reason từ body
        detail_id = request.data.get('detail_id')
        return_reason = request.data.get('reason')

        if not detail_id or not return_reason:
            return Response({
                "status": "error",
                "message": "Cả detail_id và reason đều là bắt buộc.",
                "data": None
            }, status=status.HTTP_400_BAD_REQUEST)

        # Kiểm tra xem OrderDetail với detail_id có tồn tại không
        try:
            order_detail = OrderDetail.objects.get(detail_id=detail_id)
        except OrderDetail.DoesNotExist:
            return Response({
                "status": "error",
                "message": "Không tìm thấy OrderDetail với detail_id này.",
                "data": None
            }, status=status.HTTP_404_NOT_FOUND)

        # Kiểm tra nếu đã có yêu cầu trả vé cho order_detail này
        if TicketReturn.objects.filter(detail=order_detail).exists():
            return Response({
                "status": "error",
                "message": "Đã có yêu cầu trả vé cho đơn hàng này.",
                "data": None
            }, status=status.HTTP_400_BAD_REQUEST)

        # Kiểm tra thời gian trận đấu, chỉ cho phép trả vé nếu thời gian trận đấu chưa qua
        match_time = order_detail.pricing.match.match_time if order_detail.pricing.match else None
        if match_time and match_time <= timezone.now():
            return Response({
                "status": "error",
                "message": "Không thể trả vé vì trận đấu đã qua.",
                "data": None
            }, status=status.HTTP_400_BAD_REQUEST)

        # Tạo TicketReturn mới
        ticket_return = TicketReturn(
            detail=order_detail,
            return_reason=return_reason,
            return_status='pending',  # Trạng thái mặc định khi yêu cầu trả vé
        )
        ticket_return.save()

        return Response({
            "status": "success",
            "message": "Yêu cầu trả vé đã được tạo thành công.",
            "data": {
                "return_id": ticket_return.return_id,
                "detail_id": ticket_return.detail.detail_id,
                "return_reason": ticket_return.return_reason,
                "return_status": ticket_return.return_status,
                "return_time": ticket_return.return_time,
            }
        }, status=status.HTTP_201_CREATED)


from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .serializers import PaymentSerializer
from .models import Order, Payment
import time

class CashCardPaymentAPIView(APIView):
    """
    API lưu payment ngay lập tức khi khách chọn thanh toán bằng tiền mặt hoặc thẻ.
    """

    def post(self, request, *args, **kwargs):
        order_id = request.data.get('order_id')
        payment_method = request.data.get('payment_method')

        # Chỉ chấp nhận 'cash' hoặc 'card'
        if payment_method not in ('cash', 'card'):
            return Response(
                {"error": "Phương thức thanh toán phải là tiền mặt hoặc thẻ."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Lấy order, nếu không tồn tại trả về lỗi
        try:
            order = Order.objects.get(order_id=order_id)
        except Order.DoesNotExist:
            return Response(
                {"error": "Đơn đặt hàng không tồn tại."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Tạo dữ liệu cho Payment
        payment_data = {
            'order': order.order_id,
            'payment_method': payment_method,
            'payment_status': 'success',  # Thanh toán ngay = success
            'transaction_code': f"{payment_method.upper()}-{order.order_id}-{int(time.time())}"
        }

        serializer = PaymentSerializer(data=payment_data)
        if not serializer.is_valid():
            return Response(
                {"status": "error", "errors": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Lưu payment và cập nhật trạng thái đơn hàng
        payment = serializer.save()
        order.order_status = 'received'

        agg = order.order_details.aggregate(total=Sum('price'))
        order.total_amount = agg['total'] or 0
        order.save()

        # Sử dụng serializer để validate và lưu
        for detail in order.order_details.all():
            # Tạo nội dung QR (order_id + detail_id)
            qr_payload = f"{order.order_id}|{detail.detail_id}"
            qr_img = qrcode.make(qr_payload)

            # Chuyển ảnh QR thành Base64
            buffer = BytesIO()
            qr_img.save(buffer, format='PNG')
            qr_b64 = base64.b64encode(buffer.getvalue()).decode()

            # Gán và lưu
            detail.qr_code = qr_b64
            detail.save()

        # Gửi email hóa đơn
        self.send_invoice_email(order, payment)

        return Response({
            "status": "success",
            "message": "Thanh toán thành công bằng tiền mặt/thẻ và QR code đã được sinh.",
            "payment": serializer.data
        }, status=status.HTTP_201_CREATED)

    def send_invoice_email(self, order, payment):
        subject = f"Hóa đơn thanh toán cho đơn hàng {order.order_id}"
        message = f"""
        Chào {order.user.full_name if order.user else 'Khách hàng'},
        
        Cảm ơn bạn đã mua vé tại hệ thống chúng tôi. Dưới đây là thông tin đơn hàng của bạn:

        - Mã đơn hàng: {order.order_id}
        - Tổng tiền: {order.total_amount} VND
        - Trạng thái thanh toán: {payment.payment_status}
        - Phương thức thanh toán: {payment.payment_method}
        - Mã giao dịch: {payment.transaction_code}

        Chi tiết vé:
        {self.get_order_details_string(order)}

        Chúng tôi mong muốn được phục vụ bạn trong những lần sau!

        Trân trọng,
        Hệ thống bán vé trực tuyến
        """
        
        # Tạo các hình ảnh mã QR từ base64 cho mỗi OrderDetail
        qr_code_images = []
        for order_detail in order.order_details.all():
            qr_code_image = self.create_qr_code_image_from_base64(order_detail)
            qr_code_images.append(qr_code_image)

        # Tạo email và đính kèm tất cả các mã QR
        email = EmailMessage(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [order.user.email],
        )

        # Đính kèm các QR code vào email
        for i, qr_code_image in enumerate(qr_code_images, start=1):
            email.attach(f'qr_code_{i}.png', qr_code_image, 'image/png')

        email.send(fail_silently=False)

    def get_order_details_string(self, order):
        details = []
        for order_detail in order.order_details.all():
            promotion_info = ''
            if order_detail.promotion:
                promotion = order_detail.promotion
                promotion_info = f" - Mã khuyến mãi: {promotion.promo_code}, Loại giảm giá: {promotion.discount_type}, Giá trị giảm: {promotion.discount_value} VND"

            details.append(f"- Ghế: {order_detail.seat.seat_number if order_detail.seat else 'Chưa chọn'}, Giá: {order_detail.price} VND{promotion_info}")
        return "\n".join(details)
    
    def create_qr_code_image_from_base64(self, order_detail):
        # Tạo nội dung QR (order_id + detail_id)
        qr_payload = f"{order_detail.order.order_id}|{order_detail.detail_id}"
        qr_img = qrcode.make(qr_payload)

        # Chuyển ảnh QR thành Base64
        buffer = BytesIO()
        qr_img.save(buffer, format='PNG')
        qr_b64 = base64.b64encode(buffer.getvalue()).decode()

        return qr_b64
    

class CustomerOrdersAPIView(APIView):
    def get(self, request):
        # Lấy customer_id từ tham số query string
        customer_id = request.query_params.get('customer_id')

        if not customer_id:
            return Response({
                "status": "error",
                "message": "customer_id là bắt buộc.",
                "data": None
            }, status=status.HTTP_400_BAD_REQUEST)

        # Lấy tất cả các đơn hàng của customer_id mà không có điều kiện về trạng thái
        orders = Order.objects.filter(user_id=customer_id)

        # Nếu không có đơn hàng nào
        if not orders.exists():
            return Response({
                "status": "error",
                "message": "Không tìm thấy đơn hàng nào cho khách hàng này.",
                "data": None
            }, status=status.HTTP_404_NOT_FOUND)

        # Chuẩn bị dữ liệu cho phản hồi
        data = []

        for order in orders:
            # Lấy chi tiết đơn hàng và các thông tin liên quan
            order_details_data = []
            match_data = {}
            payment = {}

            for order_detail in order.order_details.all():
                # Lấy thông tin của từng order detail mà không có điều kiện
                section_name = order_detail.pricing.section.section_name if order_detail.pricing.section else None
                match = order_detail.pricing.match if order_detail.pricing.match else None

                # Lấy thông tin khuyến mãi cho từng order detail
                promotion = {}
                if order_detail.promotion:
                    promotion = {
                        "promo_code": order_detail.promotion.promo_code,
                        "discount_type": str(order_detail.promotion.discount_type),
                        "discount_value": order_detail.promotion.discount_value,
                    }

                # Đưa section_name vào order_detail
                order_details_data.append({
                    "price": str(order_detail.price),
                    "seat": order_detail.seat.seat_number if order_detail.seat else None,
                    "qr_code": order_detail.qr_code,
                    "promotion": promotion,  # Đưa promotion vào order_detail
                    "section_name": section_name  # Đưa section_name vào order_detail
                })

            # Thông tin về trận đấu (match)
            if match:
                match_data = {
                    "match_time": match.match_time,
                    "league": match.league.league_name if match.league else None,
                    "team_1": match.team_1.team_name if match.team_1 else None,
                    "team_2": match.team_2.team_name if match.team_2 else None,
                    "stadium_name": match.stadium.stadium_name if match.stadium else None,
                    "league_name": match.league.league_name if match.league else None,
                }

            # Thông tin về thanh toán
            if order.order_status == 'cancelled':
                payment = {}
            elif getattr(order, 'payment', None):
                payment = {
                    "payment_method": order.payment.payment_method,
                    "payment_status": order.payment.payment_status,
                    "transaction_code": order.payment.transaction_code,
                    "created_at": order.payment.created_at,
                }

            # Thêm thông tin đơn hàng vào data
            data.append({
                "order_id": order.order_id,
                "user": order.user.id if order.user else None,
                "total_amount": str(order.total_amount),
                "order_status": order.order_status,
                "order_method": order.order_method,
                "created_at": order.created_at,
                "order_details": order_details_data,
                "match": match_data,
                "payment": payment
            })

        # Trả về dữ liệu dưới dạng JSON
        return Response({
            "status": "success",
            "message": "Danh sách đơn hàng đã được lấy thành công.",
            "data": data
        }, status=status.HTTP_200_OK)

from django.shortcuts import redirect
import urllib.parse

def payment_result_view(request):
    # 1. Lấy thông tin từ MoMo trả về
    result_code = request.GET.get('resultCode')
    order_id = request.GET.get('orderId') 
    message = request.GET.get('message', '')

    # 2. ĐỊA CHỈ TRANG WEB FRONTEND (LIVE SERVER)
    # Đảm bảo đường dẫn này chính xác 100% trên máy bạn
    FRONTEND_URL = "http://127.0.0.1:5500/pages/customer/qrcode.html" 
    
    # 3. Chuyển hướng
    # Lời khuyên: Hãy giữ nguyên tên tham số (orderId, resultCode) để JS dễ xử lý
    
    if str(result_code) == '0':
        # Thành công
        # Ta gửi lại 'orderId' (đúng format JS cần) và 'resultCode=0'
        return redirect(f"{FRONTEND_URL}?resultCode=0&orderId={order_id}&message=Success")
    else:
        # Thất bại
        # Cần mã hóa tin nhắn lỗi (vì có thể chứa tiếng Việt/ký tự đặc biệt)
        encoded_message = urllib.parse.quote(message)
        return redirect(f"{FRONTEND_URL}?resultCode={result_code}&orderId={order_id}&message={encoded_message}")

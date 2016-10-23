FROM python:2.7

RUN pip install pyserial
COPY cafe_server.py ./

CMD python cafe_server.py
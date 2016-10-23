FROM python:2.7

RUN pip install pyserial
WORKDIR /
COPY cafe_server.py /cafe_server.py

CMD python cafe_server.py
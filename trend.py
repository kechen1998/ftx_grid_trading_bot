# coding=utf-8

import ccxt
import datetime
import time
import ta
import numpy as np
import pandas as pd
import simplejson as json

COLOR_RESET = "\033[0;0m"
COLOR_GREEN = "\033[0;32m"
COLOR_RED = "\033[1;31m"
COLOR_BLUE = "\033[1;34m"
COLOR_WHITE = "\033[1;37m"
LOGFILE = ""


class TrendTrader:
    order_list = []

    def __init__(self, exchange, symbols, amount=0, update_exposure=10.):
        self.symbols = symbols
        self.exchange = exchange
        self.exposure = amount
        self.resolution = '1h'
        self.desired_pos = {}
        self.update_exposure = update_exposure
        pass

    def calculate_desired_pos(self):
        self.send_request('clear_open_order')
        btc_data = self.send_request("ohlcv", 'BTC-PERP')
        df_btc = pd.DataFrame(btc_data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']).set_index(
            'timestamp')
        for symbol in self.symbols:
            ohlcv_list = self.send_request("ohlcv", symbol)
            df_temp = pd.DataFrame(ohlcv_list,
                                   columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']).set_index(
                'timestamp')
            mcad = ta.trend.macd(np.log(df_temp['close'] / df_btc['close'])).iloc[-1]
            self.desired_pos[symbol] = self.exposure * (1 if mcad > 0 else -1)

    def update_pos(self):
        self.send_request('clear_open_order')
        position_list = self.send_request("get_pos")
        exposures = {}
        for symbol in self.symbols:
            positions = [pos for pos in position_list if pos['symbol'] == symbol]
            exposures[symbol] = np.sum([float(pos['info']['netSize']) for pos in positions])

        for symbol in self.symbols:
            bid_price, ask_price = self.send_request("get_bid_ask_price", symbol)
            side = 'buy'
            target_price = bid_price
            current_exp = exposures[symbol] * (bid_price+ask_price)/2
            d_pos = self.desired_pos[symbol] - current_exp
            msg = f"{symbol} desired position: {self.desired_pos[symbol]}, current position {current_exp}"
            log(msg)
            if d_pos < 0:
                side = 'sell'
                target_price = ask_price
            try:
                pos_usd = np.minimum(np.abs(d_pos), self.update_exposure)
                self.send_request("place_order", symbol, side, target_price, pos_usd/target_price)
            except ccxt.ExchangeError as e:
                log(str(e))
                continue

    def send_request(self, task, symbol=None, input1=None, input2=None, input3=None):
        tries = 3
        for i in range(tries):
            try:
                if task == "get_bid_ask_price":
                    ticker = self.exchange.fetch_ticker(symbol)
                    return ticker["bid"], ticker["ask"]

                elif task == "get_order":
                    return self.exchange.fetchOrder(symbol)["info"]

                elif task == 'get_pos':
                    return self.exchange.fetch_positions()

                elif task == 'clear_open_order':
                    self.exchange.cancel_all_orders()
                    self.order_list = []

                elif task == 'ohlcv':
                    return self.exchange.fetch_ohlcv(symbol, timeframe=self.resolution)

                elif task == "place_order" and input3 > 0.:
                    side = input1
                    price = input2
                    size = input3
                    if side == "buy":
                        orderid = self.exchange.create_limit_buy_order(symbol, size, price, params={'postOnly':True})["info"]["id"]
                    else:
                        orderid = self.exchange.create_limit_sell_order(symbol, size, price, params={'postOnly':True})["info"]["id"]
                    return orderid

                else:
                    return None
            except ccxt.BaseError as e:
                if i < tries - 1:  # i is zero indexed
                    log(str(e))
                    time.sleep(0.5)
                    continue
                else:
                    log(str(e))
                    raise
            break


def log(msg):
    timestamp = datetime.datetime.now().strftime("%b %d %Y %H:%M:%S ")
    s = "[%s] %s:%s %s" % (timestamp, COLOR_WHITE, COLOR_RESET, msg)
    print(s)
    try:
        f = open(LOGFILE, "a")
        f.write(s + "\n")
        f.close()
    except:
        pass


def read_setting():
    with open('trend.json') as json_file:
        return json.load(json_file)


config = read_setting()
LOGFILE = config["LOGFILE"]

exchange = ccxt.ftx({
    'verbose': False,
    'apiKey': config["apiKey"],
    'secret': config["secret"],
    'enableRateLimit': True,
    'headers': {'FTX-SUBACCOUNT': config["sub_account"],
    },
})

exchange_markets = exchange.load_markets()

main_job = TrendTrader(exchange, config["symbol"], config["amount"], config["update_exposure"])
main_job.calculate_desired_pos()
while True:
    try:
        if np.mod(datetime.datetime.now().minute, 15) == 0:
            print("Loop in :", datetime.datetime.now())
            if datetime.datetime.now().minute == 0:
                main_job.calculate_desired_pos()
            main_job.update_pos()
    except ccxt.BaseError as e:
        log(str(e))
        pass
    time.sleep(60)

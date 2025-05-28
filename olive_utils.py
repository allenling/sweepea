

import pika

from olive.common import OliveTaskMessage


def submit_message(amqp_url, exchange, routing_key, body):

    parameters = pika.URLParameters(amqp_url)

    connection = pika.BlockingConnection(parameters)

    channel = connection.channel()

    channel.basic_publish(exchange,
                          routing_key,
                          body,
                          pika.BasicProperties(content_type="text/plain",
                                               delivery_mode=pika.DeliveryMode.Transient))

    connection.close()
    return



def main():
    from olive.common import OliveAppConfig
    url = "amqp://guest:guest@localhost:5672/%2F"
    olive_config = OliveAppConfig()
    x_name = olive_config.amqp_config.exchange_name
    routing_key = olive_config.amqp_config.routing_key
    msg = OliveTaskMessage(func="olive.tasks.sleep_n",
                           args=[10])
    submit_message(url, x_name, routing_key, msg.to_str())
    return


if __name__ == "__main__":
    main()

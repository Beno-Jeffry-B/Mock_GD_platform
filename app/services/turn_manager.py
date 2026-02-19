from app.services.participants import generate_participant_response


def handle_user_turn(session, message):

    session.history.append(("user", message))

    name, response = generate_participant_response(session.topic, session.history)

    session.history.append((name, response))

    return name, response
